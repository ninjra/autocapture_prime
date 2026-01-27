"""Gate: run static analysis tools when available."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _module_exists(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _run(cmd: list[str]) -> int:
    result = subprocess.run(cmd)
    return result.returncode


def _tool_python() -> str | None:
    env_path = os.environ.get("AUTO_CAPTURE_TOOL_PYTHON")
    if env_path and Path(env_path).exists():
        return env_path
    candidate = Path(".dev") / "tools_venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return None


def main() -> int:
    failures = 0

    tool_python = _tool_python()
    if _module_exists("ruff") or shutil.which("ruff"):
        failures += _run([sys.executable, "-m", "ruff", "check", "."])
    elif tool_python:
        failures += _run([tool_python, "-m", "ruff", "check", "."])
    else:
        print("SKIP: ruff not installed")

    if _module_exists("mypy") or shutil.which("mypy"):
        failures += _run([sys.executable, "-m", "mypy", "."])
    elif tool_python:
        failures += _run([tool_python, "-m", "mypy", "."])
    else:
        print("SKIP: mypy not installed")

    if failures:
        print("FAIL: static analysis")
        return 1
    print("OK: static analysis")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
