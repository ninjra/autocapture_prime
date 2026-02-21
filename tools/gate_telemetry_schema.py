#!/usr/bin/env python3
"""Gate: telemetry payload schema sanity for latest entries."""

from __future__ import annotations

import json
import sys
from typing import Any

from autocapture_nx.kernel.telemetry import telemetry_snapshot


REQUIRED_FIELDS = (
    "schema_version",
    "category",
    "ts_utc",
    "run_id",
    "stage",
    "duration_ms",
    "outcome",
    "error_code",
)


def _validate_latest(latest: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category, payload in sorted(latest.items(), key=lambda item: str(item[0])):
        missing = []
        if not isinstance(payload, dict):
            missing = list(REQUIRED_FIELDS)
            payload = {}
        for field in REQUIRED_FIELDS:
            if field not in payload:
                missing.append(field)
        rows.append(
            {
                "category": str(category),
                "ok": len(missing) == 0,
                "missing": missing,
            }
        )
    return rows


def main() -> int:
    snapshot = telemetry_snapshot()
    latest = snapshot.get("latest", {}) if isinstance(snapshot.get("latest"), dict) else {}
    checks = _validate_latest(latest)
    payload = {
        "schema_version": 1,
        "ok": all(bool(row.get("ok", False)) for row in checks),
        "checks": checks,
    }
    if len(checks) == 0:
        payload["ok"] = True
        payload["reason"] = "no_data"
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0 if bool(payload.get("ok", False)) else 2


if __name__ == "__main__":
    raise SystemExit(main())

