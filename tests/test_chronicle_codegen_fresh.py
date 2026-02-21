from __future__ import annotations

import subprocess
from pathlib import Path
import unittest


class ChronicleCodegenFreshTests(unittest.TestCase):
    def test_codegen_stamp_is_fresh(self) -> None:
        root = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [".venv/bin/python", "tools/chronicle_codegen.py", "--check"],
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout)
        self.assertIn("fresh", proc.stdout.lower())


if __name__ == "__main__":
    unittest.main()
