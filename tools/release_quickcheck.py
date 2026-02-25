#!/usr/bin/env python3
"""Operator quickcheck for release/golden pipeline status."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _latest_lineage_report(root: Path) -> Path | None:
    if not root.exists():
        return None
    candidates = sorted(
        root.glob("*/stage1_stage2_lineage_queryability.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _extract_reason_candidates(payload: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for key in ("failure_reasons", "strict_failure_causes"):
        raw = payload.get(key)
        if isinstance(raw, list):
            reasons.extend(str(item) for item in raw if str(item).strip())
        elif isinstance(raw, dict):
            reasons.extend(str(item) for item in raw.keys() if str(item).strip())
    if isinstance(payload.get("top_failure_key"), str) and str(payload.get("top_failure_key")).strip():
        reasons.append(str(payload.get("top_failure_key")).strip())
    return reasons


def _popup_failure_reasons(popup: dict[str, Any], popup_misses: dict[str, Any] | None) -> list[str]:
    reasons: list[str] = []
    sample = _to_int(popup.get("sample_count", 0))
    accepted = _to_int(popup.get("accepted_count", 0))
    failed = _to_int(popup.get("failed_count", 0))
    if sample > 0 and accepted < sample:
        reasons.append("popup.accepted_below_sample")
    if failed > 0:
        reasons.append("popup.failed_nonzero")
    rows = popup.get("rows", []) if isinstance(popup.get("rows", []), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        reason = str(row.get("failure_reason") or "").strip()
        if reason:
            reasons.append(reason)
    if isinstance(popup_misses, dict):
        reason_counts = popup_misses.get("failure_reason_counts")
        if isinstance(reason_counts, dict):
            for key, count in reason_counts.items():
                if _to_int(count, 0) > 0 and str(key).strip():
                    reasons.append(str(key))
    return reasons


def build_quickcheck(*, root: Path) -> dict[str, Any]:
    release_path = root / "artifacts/release/release_gate_latest.json"
    popup_path = root / "artifacts/query_acceptance/popup_regression_latest.json"
    popup_misses_path = root / "artifacts/query_acceptance/popup_regression_misses_latest.json"
    q40_path = root / "artifacts/advanced10/q40_matrix_latest.json"
    temporal_path = root / "artifacts/temporal40/temporal40_gate_latest.json"
    real_corpus_path = root / "artifacts/real_corpus_gauntlet/latest/strict_matrix.json"
    lineage_path = _latest_lineage_report(root / "artifacts/lineage")

    release = _load_json(release_path)
    popup = _load_json(popup_path)
    popup_misses = _load_json(popup_misses_path)
    q40 = _load_json(q40_path)
    temporal = _load_json(temporal_path)
    real_corpus = _load_json(real_corpus_path)
    lineage = _load_json(lineage_path) if isinstance(lineage_path, Path) else None

    missing_artifacts: list[str] = []
    for path, payload in (
        (release_path, release),
        (popup_path, popup),
        (q40_path, q40),
        (temporal_path, temporal),
        (real_corpus_path, real_corpus),
    ):
        if payload is None:
            missing_artifacts.append(str(path))

    stage_summary = {}
    if isinstance(lineage, dict):
        summary = lineage.get("summary", {}) if isinstance(lineage.get("summary", {}), dict) else {}
        stage_summary = {
            "frames_total": _to_int(summary.get("frames_total", 0)),
            "frames_queryable": _to_int(summary.get("frames_queryable", 0)),
            "frames_blocked": _to_int(summary.get("frames_blocked", 0)),
            "lineage_complete": _to_int(summary.get("lineage_complete", 0)),
            "lineage_incomplete": _to_int(summary.get("lineage_incomplete", 0)),
            "lineage_path": str(lineage_path) if isinstance(lineage_path, Path) else "",
        }
    else:
        stage_summary = {
            "frames_total": 0,
            "frames_queryable": 0,
            "frames_blocked": 0,
            "lineage_complete": 0,
            "lineage_incomplete": 0,
            "lineage_path": str(lineage_path) if isinstance(lineage_path, Path) else "",
        }

    statuses = {
        "release_gate_ok": bool(isinstance(release, dict) and release.get("ok") is True),
        "popup_strict_ok": bool(isinstance(popup, dict) and popup.get("ok") is True),
        "q40_strict_ok": bool(isinstance(q40, dict) and q40.get("ok") is True),
        "temporal40_strict_ok": bool(isinstance(temporal, dict) and temporal.get("ok") is True),
        "real_corpus_strict_ok": bool(isinstance(real_corpus, dict) and real_corpus.get("ok") is True),
    }
    all_ok = all(bool(v) for v in statuses.values()) and len(missing_artifacts) == 0

    reason_counter: Counter[str] = Counter()
    if isinstance(release, dict) and not bool(release.get("ok", False)):
        for reason in _extract_reason_candidates(release):
            reason_counter[str(reason)] += 1
    if isinstance(popup, dict) and not bool(popup.get("ok", False)):
        for reason in _popup_failure_reasons(popup, popup_misses):
            reason_counter[str(reason)] += 1
    if isinstance(q40, dict) and not bool(q40.get("ok", False)):
        for reason in _extract_reason_candidates(q40):
            reason_counter[str(reason)] += 1
    if isinstance(temporal, dict) and not bool(temporal.get("ok", False)):
        for reason in _extract_reason_candidates(temporal):
            reason_counter[str(reason)] += 1
    if isinstance(real_corpus, dict) and not bool(real_corpus.get("ok", False)):
        for reason in _extract_reason_candidates(real_corpus):
            reason_counter[str(reason)] += 1
    for path in missing_artifacts:
        reason_counter[f"missing_artifact:{path}"] += 1
    top_failure_reasons = [key for key, _count in reason_counter.most_common(8)]

    q40_counts = {
        "matrix_total": _to_int((q40 or {}).get("matrix_total", 0)),
        "matrix_evaluated": _to_int((q40 or {}).get("matrix_evaluated", 0)),
        "matrix_skipped": _to_int((q40 or {}).get("matrix_skipped", 0)),
        "matrix_failed": _to_int((q40 or {}).get("matrix_failed", 0)),
        "source_tier": str((q40 or {}).get("source_tier") or ""),
    }
    temporal_counts_src = (temporal or {}).get("counts", {}) if isinstance((temporal or {}).get("counts", {}), dict) else {}
    temporal_counts = {
        "evaluated": _to_int(temporal_counts_src.get("evaluated", 0)),
        "skipped": _to_int(temporal_counts_src.get("skipped", 0)),
        "failed": _to_int(temporal_counts_src.get("failed", 0)),
    }
    popup_counts = {
        "sample_count": _to_int((popup or {}).get("sample_count", 0)),
        "accepted_count": _to_int((popup or {}).get("accepted_count", 0)),
        "failed_count": _to_int((popup or {}).get("failed_count", 0)),
    }
    real_counts = {
        "matrix_total": _to_int((real_corpus or {}).get("matrix_total", 0)),
        "matrix_evaluated": _to_int((real_corpus or {}).get("matrix_evaluated", 0)),
        "matrix_skipped": _to_int((real_corpus or {}).get("matrix_skipped", 0)),
        "matrix_failed": _to_int((real_corpus or {}).get("matrix_failed", 0)),
    }

    return {
        "schema_version": 1,
        "ok": bool(all_ok),
        "ts_utc": _utc_iso(),
        "statuses": statuses,
        "counts": {
            "popup": popup_counts,
            "q40": q40_counts,
            "temporal40": temporal_counts,
            "real_corpus": real_counts,
        },
        "stage_coverage": stage_summary,
        "top_failure_reasons": top_failure_reasons,
        "missing_artifacts": missing_artifacts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quick operator status for strict golden pipeline readiness.")
    parser.add_argument("--repo-root", default="")
    parser.add_argument("--output", default="artifacts/release/release_quickcheck_latest.json")
    parser.add_argument("--strict-exit", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args(argv)

    root = Path(str(args.repo_root)).expanduser().resolve() if str(args.repo_root).strip() else Path(__file__).resolve().parents[1]
    payload = build_quickcheck(root=root)
    out_path = root / str(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": bool(payload.get("ok", False)), "output": str(out_path.resolve())}, sort_keys=True))
    if bool(args.strict_exit) and not bool(payload.get("ok", False)):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
