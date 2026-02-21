from __future__ import annotations

import subprocess
from pathlib import Path
import unittest


class ChronicleContractDriftGateTests(unittest.TestCase):
    def test_gate_passes_with_current_pins(self) -> None:
        root = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [".venv/bin/python", "tools/gate_chronicle_contract_drift.py"],
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout)
        self.assertIn("pinned", proc.stdout.lower())


if __name__ == "__main__":
    unittest.main()
