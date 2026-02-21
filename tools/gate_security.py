"""Gate: security regression tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
import sys
import subprocess
import socket
import os


def _socket_available() -> bool:
    try:
        s = socket.socket()
        s.close()
        return True
    except OSError:
        return False


def _localhost_bind_available() -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", 0))
        finally:
            s.close()
        return True
    except OSError:
        return False


def main() -> int:
    # NOTE: `tests/` is intentionally not a Python package (no `tests/__init__.py`).
    # Add it to sys.path and load by module name.
    checks = [
        "test_plugin_network_block",
        "test_encrypted_store_fail_loud",
        "test_sanitizer_no_raw_pii",
        "test_policy_gate",
        "test_sqlcipher_roundtrip",
        "test_plugin_sandbox",
    ]
    if _socket_available():
        checks.insert(0, "test_network_guard")
    if _localhost_bind_available():
        checks.append("test_egress_gateway")
    if os.name == "nt":
        checks.append("test_keyring_migration_windows")
    summary = {"schema_version": 1, "checks": []}
    failed = False
    root = Path(__file__).resolve().parents[1]
    tests_dir = root / "tests"
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    for module in checks:
        suite = unittest.defaultTestLoader.loadTestsFromName(module)
        runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=1)
        result = runner.run(suite)
        status = "pass"
        skip_reason = None
        if result.failures or result.errors:
            status = "fail"
            failed = True
        elif result.testsRun > 0 and len(result.skipped) == result.testsRun:
            status = "skip"
            skip_reason = "; ".join(reason for _test, reason in result.skipped)
        summary["checks"].append(
            {
                "name": f"tests/{module}.py",
                "status": status,
                "skipped": len(result.skipped),
                "failures": len(result.failures),
                "errors": len(result.errors),
                "skip_reason": skip_reason,
            }
        )
    # SEC-09: repo-wide secret scanning gate.
    try:
        proc = subprocess.run(
            [sys.executable, "tools/gate_secrets.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
        )
        status = "pass" if proc.returncode == 0 else "fail"
        if proc.returncode != 0:
            failed = True
        summary["checks"].append(
            {
                "name": "tools.gate_secrets",
                "status": status,
                "skipped": 0,
                "failures": 0,
                "errors": 0 if proc.returncode == 0 else 1,
                "skip_reason": None,
                "output": proc.stdout[-4000:],
            }
        )
    except Exception as exc:
        failed = True
        summary["checks"].append(
            {
                "name": "tools.gate_secrets",
                "status": "fail",
                "skipped": 0,
                "failures": 0,
                "errors": 1,
                "skip_reason": None,
                "output": f"exception:{type(exc).__name__}:{exc}",
            }
        )
    out = Path("artifacts") / "security"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gate_security.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
