from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path


class Q40UIASyntheticRunnerTests(unittest.TestCase):
    def test_runner_dry_run_emits_strict_contract(self) -> None:
        script = Path("tools/run_q40_uia_synthetic.sh")
        proc = subprocess.run(
            ["bash", str(script), "tests/fixtures/state_golden.json", "--dry-run"],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["dry_run"])
        self.assertTrue(payload["strict"])
        self.assertEqual(int(payload["expected_total"]), 40)

    def test_runner_rejects_invalid_mode(self) -> None:
        script = Path("tools/run_q40_uia_synthetic.sh")
        env = os.environ.copy()
        env["AUTOCAPTURE_Q40_SYNTH_UIA_MODE"] = "bad_mode"
        proc = subprocess.run(
            ["bash", str(script), "tests/fixtures/state_golden.json", "--dry-run"],
            check=False,
            text=True,
            capture_output=True,
            env=env,
        )
        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "invalid_uia_mode")


if __name__ == "__main__":
    unittest.main()
