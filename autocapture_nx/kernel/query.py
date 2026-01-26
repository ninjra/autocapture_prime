"""Query pipeline orchestration."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from typing import Any


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _within_window(ts: str | None, window: dict[str, Any] | None) -> bool:
    if not window:
        return True
    start = _parse_ts(window.get("start"))
    end = _parse_ts(window.get("end"))
    current = _parse_ts(ts)
    if current is None:
        return False
    if start and current < start:
        return False
    if end and current > end:
        return False
    return True


def extract_on_demand(system, time_window: dict[str, Any] | None, limit: int = 5) -> int:
    media = system.get("storage.media")
    metadata = system.get("storage.metadata")
    ocr = system.get("ocr.engine")
    vlm = system.get("vision.extractor")

    processed = 0
    for record_id in getattr(metadata, "keys", lambda: [])():
        record = metadata.get(record_id, {})
        record_type = str(record.get("record_type", ""))
        if not record_type.startswith("evidence.capture."):
            continue
        if not _within_window(record.get("ts_utc"), time_window):
            continue
        run_id = record_id.split("/", 1)[0] if "/" in record_id else None
        if not run_id and hasattr(system, "config"):
            run_id = getattr(system, "config", {}).get("runtime", {}).get("run_id")
        run_id = run_id or "run"
        derived_id = f"{run_id}/derived.text/{record_id.replace('/', '_')}"
        if metadata.get(derived_id):
            continue
        blob = media.get(record_id)
        if not blob:
            continue
        text = ""
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                names = sorted(zf.namelist())
                if not names:
                    continue
                frame = zf.read(names[0])
            try:
                text = vlm.extract(frame).get("text", "")
            except Exception:
                text = ocr.extract(frame).get("text", "")
        except Exception:
            continue
        if text:
            metadata.put(
                derived_id,
                {
                    "record_type": "derived.text",
                    "ts_utc": record.get("ts_utc"),
                    "text": text,
                    "source_id": record_id,
                },
            )
            processed += 1
        if processed >= limit:
            break
    return processed


def run_query(system, query: str) -> dict[str, Any]:
    parser = system.get("time.intent_parser")
    retrieval = system.get("retrieval.strategy")
    answer = system.get("answer.builder")

    intent = parser.parse(query)
    time_window = intent.get("time_window")
    results = retrieval.search(query, time_window=time_window)
    if not results and system.config.get("processing", {}).get("on_query", {}).get("allow_decode_extract", True):
        extract_on_demand(system, time_window)
        results = retrieval.search(query, time_window=time_window)

    claims = []
    metadata = system.get("storage.metadata")
    for result in results:
        derived_id = result.get("derived_id")
        record = metadata.get(derived_id or result["record_id"], {})
        text = record.get("text", "")
        claims.append(
            {
                "text": text or f"Matched record {result['record_id']}",
                "citations": [
                    {
                        "span_id": result["record_id"],
                        "source": "local",
                        "offset_start": 0,
                        "offset_end": len(text),
                    }
                ],
            }
        )
    answer_obj = answer.build(claims)
    return {"intent": intent, "results": results, "answer": answer_obj}
