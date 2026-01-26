"""Conflict gate for answer reconciliation."""

from __future__ import annotations

import importlib


def run() -> dict:
    issues: list[str] = []
    try:
        conflict = importlib.import_module("autocapture.memory.conflict")
    except Exception as exc:
        return {"ok": False, "issues": [f"missing_conflict_module:{exc}"]}

    if not hasattr(conflict, "detect_conflicts"):
        issues.append("detect_conflicts_missing")
        return {"ok": False, "issues": issues}

    sample_claims = [
        {"id": "c1", "text": "The device is on", "subject": "device", "value": "on"},
        {"id": "c2", "text": "The device is off", "subject": "device", "value": "off"},
    ]
    detected = conflict.detect_conflicts(sample_claims)
    if not detected:
        issues.append("no_conflicts_detected")
    return {"ok": len(issues) == 0, "issues": issues, "sample_conflicts": detected}
