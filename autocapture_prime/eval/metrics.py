from __future__ import annotations

import json
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _append_row(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def record_ingest_metric(storage_root: Path, summary: dict[str, Any]) -> None:
    rows = summary.get("rows", {}) if isinstance(summary, dict) else {}
    row = {
        "record_type": "derived.eval.ingest_metric",
        "ts_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "session_id": str(summary.get("session_id") or ""),
        "id_switches": int(summary.get("id_switches") or 0),
        "rows_frames": int(rows.get("frames", 0)),
        "rows_input_events": int(rows.get("input_events", 0)),
        "rows_ocr_spans": int(rows.get("ocr_spans", 0)),
        "rows_elements": int(rows.get("elements", 0)),
        "rows_tracks": int(rows.get("tracks", 0)),
    }
    _append_row(Path(storage_root) / "metrics" / "ingest_metrics.ndjson", row)


def record_qa_metric(
    storage_root: Path,
    *,
    query: str,
    model: str,
    retrieval_hits: int,
    latency_ms: float,
    plugin_path: list[str] | None = None,
    confidence: float = 0.0,
    feedback_state: str = "unreviewed",
    evidence_order_hash: str = "",
) -> None:
    path = [str(item).strip() for item in (plugin_path or []) if str(item).strip()]
    query_text = str(query)
    row = {
        "record_type": "derived.eval.qa_latency",
        "ts_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "query": query_text,
        "query_sha256": sha256(query_text.encode("utf-8")).hexdigest(),
        "model": str(model),
        "retrieval_hits": int(retrieval_hits),
        "latency_ms": float(latency_ms),
        "plugin_path": path,
        "confidence": float(max(0.0, min(1.0, confidence))),
        "feedback_state": str(feedback_state or "unreviewed"),
        "evidence_order_hash": str(evidence_order_hash or ""),
    }
    _append_row(Path(storage_root) / "metrics" / "qa_metrics.ndjson", row)
