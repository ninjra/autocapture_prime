"""Gate: Phase 3 storage scaling + durability checks."""

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
        "tests.test_sqlcipher_store",
        "tests.test_sqlcipher_roundtrip",
        "tests.test_sqlcipher_migration",
        "tests.test_sqlcipher_indexes",
        "tests.test_storage_append_only",
        "tests.test_storage_encrypted",
        "tests.test_storage_compaction",
        "tests.test_storage_forecast",
        "tests.test_storage_recovery_scanner",
        "tests.test_storage_migrations",
        "tests.test_storage_migrate",
        "tests.test_storage_retention",
        "tests.test_no_deletion_mode",
        "tests.test_encrypted_blob_store",
        "tests.test_blob_encryption_roundtrip",
        "tests.test_integrity_sweep_stale",
        "tests.test_derived_records",
        "tests.test_key_export_import_roundtrip",
    ]
    summary = {"schema_version": 1, "checks": []}
    failed = False
    for module in checks:
        status, payload = _run_suite(module)
        summary["checks"].append(payload)
        if status == "fail":
            failed = True
    out = Path("artifacts") / "phase3"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gate_phase3.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
