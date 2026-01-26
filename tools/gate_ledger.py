"""Gate: ledger chain and anchor golden tests."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "unittest",
        "tests/test_ledger_anchor_golden.py",
        "-q",
    ]
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
