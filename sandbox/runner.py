import pathlib
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field


@dataclass
class CodeResult:
    verdict: str = 'ok'
    output: str = ''
    details: str = ''


def _normalize(text: str) -> str:
    lines = (text or '').splitlines()
    return '\n'.join(line.rstrip() for line in lines).strip()


class SubprocessRunner:
    def run(self, code, input_data='', time_limit_ms=1000):
        with tempfile.TemporaryDirectory(prefix='sandbox_') as temp_dir:
            script_path = pathlib.Path(temp_dir) / 'solution.py'
            script_path.write_text(code, encoding='utf-8')
            try:
                proc = subprocess.run(
                    [sys.executable, str(script_path)],
                    input=input_data,
                    capture_output=True,
                    text=True,
                    timeout=max(time_limit_ms / 1000, 0.1),
                    cwd=temp_dir,
                )
            except subprocess.TimeoutExpired:
                return CodeResult('tle', details=f'Превышен лимит времени ({time_limit_ms} мс)')
            if proc.returncode != 0:
                return CodeResult('re', details=(proc.stderr or '')[-2000:])
            return CodeResult('ok', output=proc.stdout)

    def check(self, code, input_data, expected_output, time_limit_ms=1000):
        result = self.run(code, input_data, time_limit_ms)
        if result.verdict != 'ok':
            return result
        if _normalize(result.output) != _normalize(expected_output):
            result.verdict = 'wa'
            result.details = (
                f'Ожидалось: {expected_output!r}\nПолучено: {result.output!r}'
            )
        return result


def get_runner():
    return SubprocessRunner()
