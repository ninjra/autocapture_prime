"""Run the full local test + invariant suite in a single command."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Iterable


def _run(cmd: list[str], env: dict[str, str]) -> int:
    result = subprocess.run(cmd, env=env)
    if result.returncode != 0:
        print(f"FAILED: {' '.join(cmd)}")
    return result.returncode


def _commands() -> Iterable[list[str]]:
    py = sys.executable
    return [
        [py, "-m", "autocapture_nx", "doctor"],
        [py, "-m", "autocapture_nx", "--safe-mode", "doctor"],
        [py, "-m", "unittest", "tests/test_blueprint_spec_validation.py", "-q"],
        [py, "-m", "unittest", "discover", "-s", "tests", "-q"],
    ]


def main() -> int:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    for cmd in _commands():
        code = _run(cmd, env)
        if code != 0:
            return code
    print("OK: all tests and invariants passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
