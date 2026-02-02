"""Gate: Phase 2 capture pipeline checks."""

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
        "tests.test_capture_backend_default",
        "tests.test_capture_backend_fallback",
        "tests.test_capture_container_resolution",
        "tests.test_capture_zip_container",
        "tests.test_capture_streaming",
        "tests.test_capture_spool_idempotent",
        "tests.test_capture_content_hash",
        "tests.test_capture_partial_failure",
        "tests.test_capture_monotonic",
        "tests.test_capture_rate",
        "tests.test_capture_disk_pressure_degrade",
        "tests.test_capture_dedupe",
        "tests.test_capture_cursor_metadata",
        "tests.test_capture_window_input_refs",
        "tests.test_capture_telemetry",
        "tests.test_capture_activity_preserve_quality",
        "tests.test_capture_governor_influence",
        "tests.test_capture_drop_event",
        "tests.test_capture_resolution_boundary",
        "tests.test_capture_journal_reconcile",
        "tests.test_capture_preset",
        "tests.test_audio_callback_queue",
        "tests.test_audio_drop_event",
        "tests.test_audio_encoding",
        "tests.test_input_batching",
        "tests.test_input_activity_signal",
        "tests.test_input_activity_mode",
        "tests.test_fullscreen_halt",
        "tests.test_monitor_selection",
    ]
    summary = {"schema_version": 1, "checks": []}
    failed = False
    for module in checks:
        status, payload = _run_suite(module)
        summary["checks"].append(payload)
        if status == "fail":
            failed = True
    out = Path("artifacts") / "phase2"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gate_phase2.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
