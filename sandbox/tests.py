from django.test import SimpleTestCase, override_settings

from sandbox.runner import SubprocessRunner, _normalize, get_runner


class NormalizeTests(SimpleTestCase):
    def test_strips_trailing_spaces_and_blank_lines(self):
        self.assertEqual(_normalize(' a  \r\nb\n\n'), 'a\nb')

    def test_empty_input(self):
        self.assertEqual(_normalize(None), '')
        self.assertEqual(_normalize(''), '')


class SubprocessRunnerTests(SimpleTestCase):
    def setUp(self):
        self.runner = SubprocessRunner()

    def test_successful_run(self):
        result = self.runner.run('a = int(input())\nprint(a * 2)', input_data='21\n')
        self.assertEqual(result.verdict, 'ok')
        self.assertEqual(_normalize(result.output), '42')

    def test_check_accepts_expected_output(self):
        result = self.runner.check('print("yes")', '', 'yes')
        self.assertEqual(result.verdict, 'ok')

    def test_check_reports_wrong_answer(self):
        result = self.runner.check('print("no")', '', 'yes')
        self.assertEqual(result.verdict, 'wa')
        self.assertIn('yes', result.details)

    def test_runtime_error(self):
        result = self.runner.run('raise ValueError("boom")')
        self.assertEqual(result.verdict, 're')
        self.assertIn('boom', result.details)

    def test_syntax_error(self):
        result = self.runner.run('def broken(:')
        self.assertEqual(result.verdict, 're')

    def test_wall_time_limit(self):
        result = self.runner.run('while True:\n    pass', time_limit_ms=300)
        self.assertEqual(result.verdict, 'tle')

    def test_sleep_is_stopped(self):
        result = self.runner.run('import time\ntime.sleep(30)', time_limit_ms=300)
        self.assertEqual(result.verdict, 'tle')

    def test_memory_limit(self):
        code = (
            'data = []\n'
            'while True:\n'
            '    data.append(bytearray(1024 * 1024))\n'
        )
        result = self.runner.run(
            code, time_limit_ms=2000, memory_limit_mb=64,
        )
        self.assertIn(result.verdict, ('re', 'tle'))

    def test_output_limit(self):
        result = self.runner.run('print("x" * 200000)')
        self.assertEqual(result.verdict, 'wa')
        self.assertIn('вывода', result.details)

    def test_oversized_code_rejected(self):
        result = self.runner.run('#' * (70 * 1024))
        self.assertEqual(result.verdict, 'ce')

    def test_code_does_not_see_project_files(self):
        code = (
            'import os\n'
            'print(sorted(os.listdir(".")))\n'
        )
        result = self.runner.run(code)
        self.assertEqual(result.verdict, 'ok')
        self.assertIn('solution.py', result.output)
        self.assertNotIn('manage.py', result.output)
        self.assertNotIn('db.sqlite3', result.output)


class GetRunnerTests(SimpleTestCase):
    @override_settings(SANDBOX_RUNNER='subprocess')
    def test_subprocess_mode(self):
        self.assertIsInstance(get_runner(), SubprocessRunner)
