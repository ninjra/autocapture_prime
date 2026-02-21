"""Deterministic pillar gate reporting utilities."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


_PILLAR_ORDER = ("P1", "P2", "P3", "P4")
_PILLAR_FILES = {
    "P1": "p1_performant.json",
    "P2": "p2_accurate.json",
    "P3": "p3_secure.json",
    "P4": "p4_citable.json",
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    status: str
    duration_ms: int
    detail: str | None = None
    artifacts: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PillarResult:
    pillar: str
    ok: bool
    duration_ms: int
    started_ts_utc: str
    finished_ts_utc: str
    checks: list[CheckResult]


def _iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _generated_at(run_id: str) -> str:
    """Derive a deterministic generated_at from run_id when possible."""
    run_id = str(run_id or "")
    parts = run_id.split("-")
    if len(parts) >= 2 and len(parts[0]) == 8:
        date = parts[0]
        time_part = parts[1]
        if time_part.endswith("Z") and len(time_part) == 7:
            hhmmss = time_part[:-1]
            return f"{date[:4]}-{date[4:6]}-{date[6:8]}T{hhmmss[:2]}:{hhmmss[2:4]}:{hhmmss[4:6]}Z"
    if run_id:
        return run_id
    return _iso_utc()


def _sorted_checks(checks: Iterable[CheckResult]) -> list[CheckResult]:
    return sorted(checks, key=lambda c: c.name)


def _serialize_check(check: CheckResult) -> dict[str, Any]:
    return {
        "name": check.name,
        "ok": bool(check.ok),
        "status": str(check.status),
        "duration_ms": int(check.duration_ms),
        "detail": check.detail,
        "artifacts": sorted([str(item) for item in check.artifacts]),
        "data": dict(check.data),
    }


def _serialize_pillar(pillar: PillarResult) -> dict[str, Any]:
    return {
        "pillar": pillar.pillar,
        "ok": bool(pillar.ok),
        "duration_ms": int(pillar.duration_ms),
        "started_ts_utc": pillar.started_ts_utc,
        "finished_ts_utc": pillar.finished_ts_utc,
        "checks": [_serialize_check(check) for check in _sorted_checks(pillar.checks)],
    }


def write_reports(
    run_id: str,
    pillars: Iterable[PillarResult],
    *,
    artifacts_dir: str | Path = "artifacts/pillar_reports",
) -> dict[str, Path]:
    """Write deterministic combined + per-pillar reports."""
    report_dir = Path(artifacts_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        pillars,
        key=lambda p: (_PILLAR_ORDER.index(p.pillar) if p.pillar in _PILLAR_ORDER else 99, p.pillar),
    )
    generated_at = _generated_at(run_id)
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": generated_at,
        "ok": all(p.ok for p in ordered),
        "pillars": [_serialize_pillar(p) for p in ordered],
    }
    paths: dict[str, Path] = {}
    combined_path = report_dir / "pillar_gates.json"
    combined_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    paths["pillar_gates"] = combined_path
    for pillar in ordered:
        filename = _PILLAR_FILES.get(pillar.pillar)
        if not filename:
            continue
        pillar_payload = {
            "schema_version": 1,
            "run_id": run_id,
            "generated_at": generated_at,
            "ok": bool(pillar.ok),
            "pillar": _serialize_pillar(pillar),
        }
        pillar_path = report_dir / filename
        pillar_path.write_text(json.dumps(pillar_payload, indent=2, sort_keys=True), encoding="utf-8")
        paths[pillar.pillar] = pillar_path
    return paths
