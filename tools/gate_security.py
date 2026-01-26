"""Gate: security regression tests."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "unittest",
        "tests/test_network_guard.py",
        "tests/test_plugin_network_block.py",
        "tests/test_sanitizer_no_raw_pii.py",
        "tests/test_egress_gateway.py",
        "-q",
    ]
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
