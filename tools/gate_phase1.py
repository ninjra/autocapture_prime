"""Gate: Phase 1 correctness + immutability checks."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


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
        "tests.test_config_defaults",
        "tests.test_config_history",
        "tests.test_config",
        "tests.test_kernel_effective_config",
        "tests.test_contract_pins",
        "tests.test_journal_run_id",
        "tests.test_journal_batch",
        "tests.test_journal_typed",
        "tests.test_ledger_journal",
        "tests.test_ledger_journal_concurrency",
        "tests.test_ledger_head_hash",
        "tests.test_metadata_record_type",
        "tests.test_metadata_immutability",
        "tests.test_run_state_entries",
        "tests.test_run_manifest",
        "tests.test_encrypted_store_fail_loud",
        "tests.test_keyring_require_protection",
        "tests.test_keyring_status",
        "tests.test_key_rotation",
    ]
    if os.name == "nt":
        checks.append("tests.test_keyring_migration_windows")
    summary = {"schema_version": 1, "checks": []}
    failed = False
    for module in checks:
        status, payload = _run_suite(module)
        summary["checks"].append(payload)
        if status == "fail":
            failed = True
    out = Path("artifacts") / "phase1"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gate_phase1.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
