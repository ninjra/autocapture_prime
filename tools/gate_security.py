"""Gate: security regression tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
import sys
import subprocess


def main() -> int:
    checks = [
        "tests.test_network_guard",
        "tests.test_plugin_network_block",
        "tests.test_encrypted_store_fail_loud",
        "tests.test_sanitizer_no_raw_pii",
        "tests.test_policy_gate",
        "tests.test_egress_gateway",
        "tests.test_sqlcipher_roundtrip",
        "tests.test_plugin_sandbox",
        "tests.test_keyring_migration_windows",
    ]
    summary = {"schema_version": 1, "checks": []}
    failed = False
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
                "name": module,
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
