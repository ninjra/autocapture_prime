"""Gate: Phase 0 scaffolding + gate checks."""

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
        "tests.test_paths_package_safe",
        "tests.test_packaged_resources",
        "tests.test_paths_preferred_windows",
        "tests.test_platform_paths",
        "tests.test_directory_hashing",
        "tests.test_hashing_directory_deterministic",
        "tests.test_hashing_canonical",
        "tests.test_canonical_json",
        "tests.test_canonical_payloads",
        "tests.test_rng_guard",
        "tests.test_optional_deps_imports",
        "tests.test_optional_dependency_imports",
        "tests.test_optional_plugins_disabled",
        "tests.test_vendor_binaries_hashcheck",
        "tests.test_devtools",
        "tests.test_ids_stable",
        "tests.test_record_id_encoding",
    ]
    summary = {"schema_version": 1, "checks": []}
    failed = False
    for module in checks:
        status, payload = _run_suite(module)
        summary["checks"].append(payload)
        if status == "fail":
            failed = True
    out = Path("artifacts") / "phase0"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gate_phase0.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
