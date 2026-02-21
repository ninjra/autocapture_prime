"""Gate: vulnerability scan using pip-audit."""

from __future__ import annotations

import json
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
import socket
from datetime import datetime, timezone


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


def _parse_ts_utc(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_ignored_vuln_ids(path: Path, *, now: datetime | None = None) -> tuple[list[str], list[str]]:
    if not path.exists():
        return ([], [])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ([], [f"invalid_json:{path}"])
    entries = payload.get("ignored_ids", []) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        return ([], [f"invalid_schema:{path}"])
    at = now or datetime.now(timezone.utc)
    active: list[str] = []
    errors: list[str] = []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"invalid_entry:{idx}")
            continue
        vuln_id = str(entry.get("id") or "").strip()
        if not vuln_id:
            errors.append(f"missing_id:{idx}")
            continue
        expires_raw = str(entry.get("expires_utc") or "").strip()
        expires = _parse_ts_utc(expires_raw) if expires_raw else None
        if expires_raw and expires is None:
            errors.append(f"invalid_expiry:{vuln_id}")
            continue
        if expires is not None and expires <= at:
            errors.append(f"expired:{vuln_id}")
            continue
        active.append(vuln_id)
    return (sorted(set(active)), errors)


def main() -> int:
    runner = _runner()
    if runner is None:
        print("FAIL: pip-audit not available (install via dev extra or tooling venv)")
        return 1
    if not _network_available():
        print("SKIP: vulnerability scan (no network / DNS unavailable)")
        return 0
    ignored_ids, ignore_errors = _load_ignored_vuln_ids(Path("config") / "vuln_allowlist.json")
    if ignore_errors:
        print(f"FAIL: invalid vulnerability allowlist entries: {', '.join(ignore_errors)}")
        return 1
    cache_dir = Path(".dev") / "cache" / "pip_audit"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cmd = [*runner, "--local", "--progress-spinner", "off", "--cache-dir", str(cache_dir)]
    for vuln_id in ignored_ids:
        cmd.extend(["--ignore-vuln", vuln_id])
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("FAIL: vulnerability scan")
        return result.returncode
    print("OK: vulnerability scan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
