import sys
import unittest

from autocapture.codex.spec import ValidatorSpec
from autocapture.codex.validators import _run_command, _validator_cli_exit, _validator_cli_json


class CodexValidatorsTests(unittest.TestCase):
    def test_run_command_timeout_returns_124(self) -> None:
        result = _run_command(
            [sys.executable, "-c", "import time; time.sleep(0.25)"],
            timeout_s=0.05,
            max_output_chars=1024,
        )
        self.assertEqual(result.returncode, 124)
        self.assertIn("timeout", str(result.stderr))

    def test_run_command_caps_output(self) -> None:
        result = _run_command(
            [sys.executable, "-c", "print('x' * 5000)"],
            timeout_s=2.0,
            max_output_chars=100,
        )
        self.assertEqual(result.returncode, 0)
        self.assertLessEqual(len(str(result.stdout)), 100)

    def test_validator_cli_exit_reports_timeout(self) -> None:
        spec = ValidatorSpec(
            type="cli_exit",
            config={
                "command": [sys.executable, "-c", "import time; time.sleep(0.2)"],
                "expected_exit_code": 0,
                "timeout_s": 0.05,
            },
        )
        report = _validator_cli_exit(spec)
        self.assertFalse(report.ok)
        self.assertEqual(report.detail, "timeout")

    def test_validator_cli_json_reports_timeout(self) -> None:
        spec = ValidatorSpec(
            type="cli_json",
            config={
                "command": [sys.executable, "-c", "import time; time.sleep(0.2)"],
                "must_contain_json_keys": ["ok"],
                "timeout_s": 0.05,
            },
        )
        report = _validator_cli_json(spec)
        self.assertFalse(report.ok)
        self.assertEqual(report.detail, "timeout")


if __name__ == "__main__":
    unittest.main()
