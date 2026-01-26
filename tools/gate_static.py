"""Gate: run static analysis tools when available."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys


def _module_exists(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _run(cmd: list[str]) -> int:
    result = subprocess.run(cmd)
    return result.returncode


def main() -> int:
    failures = 0

    if _module_exists("ruff") or shutil.which("ruff"):
        failures += _run([sys.executable, "-m", "ruff", "check", "."])
    else:
        print("SKIP: ruff not installed")

    if _module_exists("mypy") or shutil.which("mypy"):
        failures += _run([sys.executable, "-m", "mypy", "."])
    else:
        print("SKIP: mypy not installed")

    if failures:
        print("FAIL: static analysis")
        return 1
    print("OK: static analysis")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
