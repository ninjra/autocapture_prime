"""Gate: vulnerability scan using pip-audit."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
import socket


def _tool_python() -> str | None:
    env_path = os.environ.get("AUTO_CAPTURE_TOOL_PYTHON")
    if env_path and Path(env_path).exists():
        return env_path
    candidate = Path(".dev") / "tools_venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return None


def _runner() -> list[str] | None:
    if shutil.which("pip-audit"):
        return ["pip-audit"]
    if importlib.util.find_spec("pip_audit") is not None:
        return [sys.executable, "-m", "pip_audit"]
    tool_python = _tool_python()
    if tool_python:
        return [tool_python, "-m", "pip_audit"]
    return None


def _network_available() -> bool:
    allow = os.environ.get("AUTO_CAPTURE_ALLOW_NETWORK")
    if allow is not None and str(allow).strip() not in {"1", "true", "yes"}:
        return False
    try:
        # DNS-only probe; avoids making outbound connections in environments that disallow it.
        socket.getaddrinfo("pypi.org", 443)
    except Exception:
        return False
    return True


def main() -> int:
    runner = _runner()
    if runner is None:
        print("FAIL: pip-audit not available (install via dev extra or tooling venv)")
        return 1
    if not _network_available():
        print("SKIP: vulnerability scan (no network / DNS unavailable)")
        return 0
    cache_dir = Path(".dev") / "cache" / "pip_audit"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cmd = [*runner, "--local", "--progress-spinner", "off", "--cache-dir", str(cache_dir)]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("FAIL: vulnerability scan")
        return result.returncode
    print("OK: vulnerability scan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
