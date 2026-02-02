"""Gate: Phase 6 security + egress hardening tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


def _run_suite(module: str) -> tuple[str, dict]:
    suite = unittest.defaultTestLoader.loadTestsFromName(module)
    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=1)
    result = runner.run(suite)
    status = "pass"
    skip_reason = None
    if result.failures or result.errors:
        status = "fail"
    elif result.testsRun > 0 and len(result.skipped) == result.testsRun:
        status = "skip"
        skip_reason = "; ".join(reason for _test, reason in result.skipped)
    return status, {
        "name": module,
        "status": status,
        "skipped": len(result.skipped),
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skip_reason": skip_reason,
    }


def main() -> int:
    checks = [
        "tests.test_network_guard",
        "tests.test_kernel_network_deny",
        "tests.test_plugin_network_block",
        "tests.test_plugin_capability_policies",
        "tests.test_plugin_filesystem_policy",
        "tests.test_win_sandbox_limits",
        "tests.test_plugin_env_sanitization",
        "tests.test_plugin_watchdog_restart",
        "tests.test_plugin_rpc_size_limit",
        "tests.test_hashing_symlink",
        "tests.test_acl_hardening",
        "tests.test_keyring_purpose_rotation",
        "tests.test_anchor",
        "tests.test_verify_integrity",
        "tests.test_security_ledger_events",
        "tests.test_tokenizer_versioning",
        "tests.test_egress_packet_ledger",
    ]
    summary = {"schema_version": 1, "checks": []}
    failed = False
    for module in checks:
        status, payload = _run_suite(module)
        summary["checks"].append(payload)
        if status == "fail":
            failed = True
    out = Path("artifacts") / "phase6"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gate_phase6.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
