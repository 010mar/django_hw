import ctypes
import logging
import math
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings

logger = logging.getLogger(__name__)

MAX_CODE_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
MAX_PROCESSES = 16
TIME_LIMIT_GRACE_MS = 500
DOCKER_OVERHEAD_SECONDS = 10
DEFAULT_DOCKER_IMAGE = 'python:3.12-alpine'

if os.name == 'nt':
    from ctypes import wintypes

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
    _JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
    _JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    _JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    _JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_TERMINATE = 0x0001

    class _JobBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ('PerProcessUserTimeLimit', ctypes.c_int64),
            ('PerJobUserTimeLimit', ctypes.c_int64),
            ('LimitFlags', wintypes.DWORD),
            ('MinimumWorkingSetSize', ctypes.c_size_t),
            ('MaximumWorkingSetSize', ctypes.c_size_t),
            ('ActiveProcessLimit', wintypes.DWORD),
            ('Affinity', ctypes.c_size_t),
            ('PriorityClass', wintypes.DWORD),
            ('SchedulingClass', wintypes.DWORD),
        ]

    class _JobIoCounters(ctypes.Structure):
        _fields_ = [
            ('ReadOperationCount', ctypes.c_uint64),
            ('WriteOperationCount', ctypes.c_uint64),
            ('OtherOperationCount', ctypes.c_uint64),
            ('ReadTransferCount', ctypes.c_uint64),
            ('WriteTransferCount', ctypes.c_uint64),
            ('OtherTransferCount', ctypes.c_uint64),
        ]

    class _JobExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ('BasicLimitInformation', _JobBasicLimitInformation),
            ('IoInfo', _JobIoCounters),
            ('ProcessMemoryLimit', ctypes.c_size_t),
            ('JobMemoryLimit', ctypes.c_size_t),
            ('PeakProcessMemoryUsed', ctypes.c_size_t),
            ('PeakJobMemoryUsed', ctypes.c_size_t),
        ]

    class _WindowsJob:
        def __init__(self, memory_mb, time_limit_ms, max_processes):
            self._handle = None
            self._kernel32 = None
            try:
                kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
                self._configure_api(kernel32)
                handle = kernel32.CreateJobObjectW(None, None)
                if not handle:
                    return
                info = _JobExtendedLimitInformation()
                info.BasicLimitInformation.LimitFlags = (
                    _JOB_OBJECT_LIMIT_PROCESS_TIME
                    | _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                    | _JOB_OBJECT_LIMIT_PROCESS_MEMORY
                    | _JOB_OBJECT_LIMIT_JOB_MEMORY
                    | _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                )
                info.BasicLimitInformation.PerProcessUserTimeLimit = (
                    time_limit_ms + TIME_LIMIT_GRACE_MS
                ) * 10_000
                info.BasicLimitInformation.ActiveProcessLimit = max_processes
                info.ProcessMemoryLimit = memory_mb * 1024 * 1024
                info.JobMemoryLimit = memory_mb * 1024 * 1024
                configured = kernel32.SetInformationJobObject(
                    handle,
                    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                    ctypes.byref(info),
                    ctypes.sizeof(info),
                )
                if not configured:
                    kernel32.CloseHandle(handle)
                    return
                self._handle = handle
                self._kernel32 = kernel32
            except (AttributeError, OSError):
                self._handle = None

        @staticmethod
        def _configure_api(kernel32):
            kernel32.CreateJobObjectW.restype = wintypes.HANDLE
            kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
            kernel32.SetInformationJobObject.restype = wintypes.BOOL
            kernel32.SetInformationJobObject.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                wintypes.LPVOID,
                wintypes.DWORD,
            ]
            kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
            kernel32.AssignProcessToJobObject.argtypes = [
                wintypes.HANDLE,
                wintypes.HANDLE,
            ]
            kernel32.TerminateJobObject.restype = wintypes.BOOL
            kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.OpenProcess.argtypes = [
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        @property
        def handle(self):
            return self._handle

        def assign(self, pid):
            if not self._handle:
                return False
            process_handle = self._kernel32.OpenProcess(
                _PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid
            )
            if not process_handle:
                return False
            try:
                return bool(
                    self._kernel32.AssignProcessToJobObject(
                        self._handle, process_handle
                    )
                )
            finally:
                self._kernel32.CloseHandle(process_handle)

        def terminate(self):
            if self._handle:
                self._kernel32.TerminateJobObject(self._handle, 1)

        def close(self):
            if self._handle:
                self._kernel32.CloseHandle(self._handle)
                self._handle = None


@dataclass
class CodeResult:
    verdict: str = 'ok'
    output: str = ''
    details: str = ''


@dataclass
class _ProcessOutcome:
    returncode: int
    stdout: bytes
    stderr: bytes
    truncated: bool
    timed_out: bool


def _normalize(text: str) -> str:
    lines = (text or '').splitlines()
    return '\n'.join(line.rstrip() for line in lines).strip()


def _decode(data) -> str:
    return (data or b'').decode('utf-8', errors='replace')


def _tail(text: str, limit: int = 2000) -> str:
    return text[-limit:]


def _code_too_large(code) -> bool:
    if not isinstance(code, str):
        return True
    return len(code.encode('utf-8')) > MAX_CODE_BYTES


def _sandbox_env(temp_path) -> dict:
    env = {
        'PATH': os.environ.get('PATH', ''),
        'PYTHONIOENCODING': 'utf-8',
        'PYTHONHASHSEED': '0',
        'PYTHONDONTWRITEBYTECODE': '1',
        'TEMP': str(temp_path),
        'TMP': str(temp_path),
    }
    for key in ('SYSTEMROOT', 'WINDIR'):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _posix_limit_wrapper(memory_mb: int, time_limit_ms: int) -> str:
    cpu_seconds = max(1, math.ceil((time_limit_ms + TIME_LIMIT_GRACE_MS) / 1000))
    return (
        'import resource,runpy,sys;'
        f'm={memory_mb * 1024 * 1024};c={cpu_seconds};'
        'resource.setrlimit(resource.RLIMIT_AS,(m,m));'
        'resource.setrlimit(resource.RLIMIT_CPU,(c,c));'
        'resource.setrlimit(resource.RLIMIT_NPROC,(64,64));'
        'resource.setrlimit(resource.RLIMIT_FSIZE,(8388608,8388608));'
        "runpy.run_path(sys.argv[1],run_name='__main__')"
    )


class _StreamPump(threading.Thread):
    def __init__(self, stream, limit):
        super().__init__(daemon=True)
        self._stream = stream
        self._limit = limit
        self._chunks = []
        self._size = 0
        self.truncated = False

    def run(self):
        read = getattr(self._stream, 'read1', self._stream.read)
        try:
            while True:
                chunk = read(8192)
                if not chunk:
                    break
                room = self._limit - self._size
                if room > 0:
                    self._chunks.append(chunk[:room])
                    self._size += min(len(chunk), room)
                if len(chunk) > room:
                    self.truncated = True
        except (OSError, ValueError):
            pass
        finally:
            try:
                self._stream.close()
            except OSError:
                pass

    @property
    def data(self):
        return b''.join(self._chunks)


class _InputPump(threading.Thread):
    def __init__(self, stream, data):
        super().__init__(daemon=True)
        self._stream = stream
        self._data = data

    def run(self):
        try:
            if self._data:
                self._stream.write(self._data)
            self._stream.close()
        except (OSError, ValueError):
            pass


def _kill_process(proc, job):
    if job is not None:
        job.terminate()
        return
    try:
        proc.kill()
    except OSError:
        pass
    if os.name != 'nt':
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass


def _cleanup_leftovers(proc, job):
    if job is not None:
        job.close()
    elif os.name != 'nt':
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass


def _execute(command, input_data, time_limit_ms, memory_limit_mb, cwd, env=None, timeout_seconds=None):
    timeout = timeout_seconds if timeout_seconds is not None else max(time_limit_ms, 1) / 1000
    kwargs = {
        'stdin': subprocess.PIPE,
        'stdout': subprocess.PIPE,
        'stderr': subprocess.PIPE,
        'cwd': str(cwd),
        'env': env,
    }
    if os.name == 'nt':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    else:
        kwargs['start_new_session'] = True
    proc = subprocess.Popen(command, **kwargs)
    job = None
    if os.name == 'nt':
        job = _WindowsJob(memory_limit_mb, time_limit_ms, MAX_PROCESSES)
        if job.handle and not job.assign(proc.pid):
            logger.warning('Не удалось применить Job Object к процессу песочницы.')
            job.close()
            job = None
    out_pump = _StreamPump(proc.stdout, MAX_OUTPUT_BYTES)
    err_pump = _StreamPump(proc.stderr, MAX_OUTPUT_BYTES)
    in_pump = _InputPump(proc.stdin, (input_data or '').encode('utf-8'))
    for pump in (out_pump, err_pump, in_pump):
        pump.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process(proc, job)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    _cleanup_leftovers(proc, job)
    for pump in (out_pump, err_pump, in_pump):
        pump.join(timeout=2)
    return _ProcessOutcome(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=out_pump.data,
        stderr=err_pump.data,
        truncated=out_pump.truncated or err_pump.truncated,
        timed_out=timed_out,
    )


class _BaseRunner:
    def run(self, code, input_data='', time_limit_ms=1000, memory_limit_mb=128):
        raise NotImplementedError

    def check(self, code, input_data, expected_output, time_limit_ms=1000, memory_limit_mb=128):
        result = self.run(code, input_data, time_limit_ms, memory_limit_mb)
        if result.verdict != 'ok':
            return result
        if _normalize(result.output) != _normalize(expected_output):
            result.verdict = 'wa'
            result.details = (
                f'Ожидалось: {expected_output!r}\nПолучено: {result.output!r}'
            )
        return result


class SubprocessRunner(_BaseRunner):
    def run(self, code, input_data='', time_limit_ms=1000, memory_limit_mb=128):
        if _code_too_large(code):
            return CodeResult('ce', details='Слишком большой объём кода.')
        memory_mb = max(int(memory_limit_mb or 0), 32)
        with tempfile.TemporaryDirectory(prefix='sandbox_') as temp_dir:
            temp_path = pathlib.Path(temp_dir).resolve()
            script_path = temp_path / 'solution.py'
            script_path.write_text(code, encoding='utf-8')
            if os.name == 'nt':
                command = [sys.executable, '-X', 'utf8', str(script_path)]
            else:
                command = [
                    sys.executable,
                    '-X',
                    'utf8',
                    '-c',
                    _posix_limit_wrapper(memory_mb, time_limit_ms),
                    str(script_path),
                ]
            outcome = _execute(
                command,
                input_data,
                time_limit_ms,
                memory_mb,
                cwd=temp_path,
                env=_sandbox_env(temp_path),
            )
        if outcome.timed_out:
            return CodeResult(
                'tle',
                details=f'Превышен лимит времени ({time_limit_ms} мс)',
            )
        if outcome.returncode != 0:
            if os.name != 'nt' and -outcome.returncode == signal.SIGXCPU:
                return CodeResult(
                    'tle',
                    details=f'Превышен лимит времени ({time_limit_ms} мс)',
                )
            return CodeResult('re', details=_tail(_decode(outcome.stderr)))
        if outcome.truncated:
            return CodeResult(
                'wa',
                output=_decode(outcome.stdout),
                details='Превышен лимит объёма вывода.',
            )
        return CodeResult('ok', output=_decode(outcome.stdout))


class DockerRunner(_BaseRunner):
    def __init__(self, image=None):
        self.image = image or getattr(
            settings, 'SANDBOX_DOCKER_IMAGE', DEFAULT_DOCKER_IMAGE
        )

    def run(self, code, input_data='', time_limit_ms=1000, memory_limit_mb=128):
        if _code_too_large(code):
            return CodeResult('ce', details='Слишком большой объём кода.')
        memory_mb = max(int(memory_limit_mb or 0), 32)
        seconds = max(time_limit_ms, 1) / 1000
        if not _ensure_image(self.image):
            return CodeResult(
                're',
                details='Не удалось подготовить изолированную среду проверки кода.',
            )
        container = f'django-sandbox-{uuid.uuid4().hex[:12]}'
        with tempfile.TemporaryDirectory(prefix='sandbox_') as temp_dir:
            temp_path = pathlib.Path(temp_dir).resolve()
            (temp_path / 'solution.py').write_text(code, encoding='utf-8')
            command = [
                'docker',
                'run',
                '--rm',
                '--interactive',
                '--name',
                container,
                '--network',
                'none',
                '--read-only',
                '--tmpfs',
                '/tmp:rw,size=32m,nosuid,nodev',
                '--memory',
                f'{memory_mb}m',
                '--memory-swap',
                f'{memory_mb}m',
                '--pids-limit',
                str(MAX_PROCESSES * 4),
                '--cpus',
                '1',
                '--cap-drop',
                'ALL',
                '--security-opt',
                'no-new-privileges',
                '--user',
                '65534:65534',
                '--workdir',
                '/tmp',
                '--volume',
                f'{temp_path}:/work:ro',
                '--entrypoint',
                'python',
                self.image,
                '-I',
                '-c',
                (
                    'import runpy,signal;'
                    f'signal.setitimer(signal.ITIMER_REAL,{seconds!r});'
                    "runpy.run_path('/work/solution.py',run_name='__main__')"
                ),
            ]
            outcome = _execute(
                command,
                input_data,
                time_limit_ms,
                memory_mb,
                cwd=temp_path,
                timeout_seconds=seconds + DOCKER_OVERHEAD_SECONDS,
            )
        if outcome.timed_out:
            _docker_kill(container)
            return CodeResult(
                'tle',
                details=f'Превышен лимит времени ({time_limit_ms} мс)',
            )
        if outcome.returncode == 142:
            return CodeResult(
                'tle',
                details=f'Превышен лимит времени ({time_limit_ms} мс)',
            )
        if outcome.returncode == 137:
            return CodeResult('re', details='Превышен лимит памяти.')
        if outcome.returncode == 125:
            logger.warning(
                'Docker sandbox failed: %s', _decode(outcome.stderr)
            )
            return CodeResult(
                're',
                details='Не удалось запустить среду проверки кода.',
            )
        if outcome.returncode != 0:
            return CodeResult('re', details=_tail(_decode(outcome.stderr)))
        if outcome.truncated:
            return CodeResult(
                'wa',
                output=_decode(outcome.stdout),
                details='Превышен лимит объёма вывода.',
            )
        return CodeResult('ok', output=_decode(outcome.stdout))


def _docker_kill(container):
    try:
        subprocess.run(
            ['docker', 'kill', container],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _ensure_image(image):
    try:
        inspect = subprocess.run(
            ['docker', 'image', 'inspect', image],
            capture_output=True,
            check=False,
            timeout=15,
        )
        if inspect.returncode == 0:
            return True
        pull = subprocess.run(
            ['docker', 'pull', image],
            capture_output=True,
            check=False,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if pull.returncode != 0:
        logger.warning('Docker pull failed: %s', _decode(pull.stderr))
        return False
    return True


@lru_cache(maxsize=1)
def docker_available() -> bool:
    if not shutil.which('docker'):
        return False
    try:
        result = subprocess.run(
            ['docker', 'info', '--format', '{{.ServerVersion}}'],
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def get_runner():
    mode = getattr(settings, 'SANDBOX_RUNNER', 'auto')
    if mode == 'subprocess':
        return SubprocessRunner()
    if mode == 'docker':
        if docker_available():
            return DockerRunner()
        logger.warning(
            'SANDBOX_RUNNER=docker, но Docker недоступен. '
            'Используется подпроцесс с ограничениями ресурсов.'
        )
        return SubprocessRunner()
    if docker_available():
        return DockerRunner()
    return SubprocessRunner()
