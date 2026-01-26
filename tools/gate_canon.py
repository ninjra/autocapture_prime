"""Gate: canonical JSON safety tests."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "unittest",
        "tests/test_canonical_json.py",
        "tests/test_canonical_payloads.py",
        "-q",
    ]
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
