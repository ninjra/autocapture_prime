"""Conflict detection utilities."""

from __future__ import annotations

from typing import Any


def detect_conflicts(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    grouped: dict[str, set[str]] = {}
    for claim in claims:
        subject = claim.get("subject")
        value = claim.get("value")
        if not subject or value is None:
            continue
        grouped.setdefault(subject, set()).add(str(value))
    for subject, values in grouped.items():
        if len(values) > 1:
            conflicts.append({"subject": subject, "values": sorted(values)})
    return conflicts
