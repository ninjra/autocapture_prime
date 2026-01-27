"""Query pipeline orchestration."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from typing import Any

from autocapture_nx.kernel.ids import encode_record_id_component


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


def extract_on_demand(
    system,
    time_window: dict[str, Any] | None,
    *,
    limit: int = 5,
    allow_ocr: bool = True,
    allow_vlm: bool = True,
    collected_ids: list[str] | None = None,
    candidate_ids: list[str] | None = None,
) -> int:
    media = system.get("storage.media")
    metadata = system.get("storage.metadata")
    ocr = system.get("ocr.engine") if allow_ocr else None
    vlm = system.get("vision.extractor") if allow_vlm else None
    event_builder = None
    if hasattr(system, "get"):
        try:
            event_builder = system.get("event.builder")
        except Exception:
            event_builder = None

    processed = 0
    if candidate_ids is not None:
        record_ids = list(dict.fromkeys(candidate_ids))
    else:
        record_ids = list(getattr(metadata, "keys", lambda: [])())
    for record_id in record_ids:
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
        derived_ids: list[tuple[str, Any, str]] = []
        encoded_source = encode_record_id_component(record_id)
        if ocr is not None:
            derived_ids.append(
                (f"{run_id}/derived.text.ocr/{encoded_source}", ocr, "ocr")
            )
        if vlm is not None:
            derived_ids.append(
                (f"{run_id}/derived.text.vlm/{encoded_source}", vlm, "vlm")
            )
        if not derived_ids:
            continue
        blob = media.get(record_id)
        if not blob:
            continue
        frame = _extract_frame(blob, record)
        if not frame:
            continue
        for derived_id, extractor, kind in derived_ids:
            if metadata.get(derived_id):
                continue
            try:
                text = extractor.extract(frame).get("text", "")
            except Exception:
                continue
            if text:
                payload = {
                    "record_type": f"derived.text.{kind}",
                    "ts_utc": record.get("ts_utc"),
                    "text": text,
                    "source_id": record_id,
                    "method": kind,
                }
                if hasattr(metadata, "put_new"):
                    try:
                        metadata.put_new(derived_id, payload)
                    except Exception:
                        continue
                else:
                    metadata.put(derived_id, payload)
                if collected_ids is not None:
                    collected_ids.append(derived_id)
                if event_builder is not None:
                    event_payload = dict(payload)
                    event_payload["derived_id"] = derived_id
                    event_builder.journal_event("derived.extract", event_payload, event_id=derived_id, ts_utc=payload["ts_utc"])
                    event_builder.ledger_entry(
                        "derived.extract",
                        inputs=[record_id],
                        outputs=[derived_id],
                        payload=event_payload,
                        entry_id=derived_id,
                        ts_utc=payload["ts_utc"],
                    )
                processed += 1
            if processed >= limit:
                break
        if processed >= limit:
            break
    return processed


def _extract_frame(blob: bytes, record: dict[str, Any]) -> bytes | None:
    container = record.get("container", {})
    container_type = container.get("type")
    if container_type == "avi_mjpeg":
        try:
            from autocapture_nx.capture.avi import AviMjpegReader

            reader = AviMjpegReader(blob)
            frame = reader.first_frame()
            reader.close()
            return frame
        except Exception:
            return None
    if container_type and container_type not in ("zip", "avi_mjpeg"):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = sorted(zf.namelist())
            if not names:
                return None
            return zf.read(names[0])
    except Exception:
        return None


def run_query(system, query: str) -> dict[str, Any]:
    parser = system.get("time.intent_parser")
    retrieval = system.get("retrieval.strategy")
    answer = system.get("answer.builder")
    event_builder = None
    if hasattr(system, "get"):
        try:
            event_builder = system.get("event.builder")
        except Exception:
            event_builder = None
    promptops_result = None
    promptops_cfg = system.config.get("promptops", {}) if hasattr(system, "config") else {}
    query_text = query
    if isinstance(promptops_cfg, dict) and bool(promptops_cfg.get("enabled", True)):
        try:
            from autocapture.promptops.engine import PromptOpsLayer

            layer = PromptOpsLayer(system.config)
            strategy = promptops_cfg.get("query_strategy", "none")
            promptops_result = layer.prepare_prompt(
                query,
                prompt_id="query",
                strategy=str(strategy) if strategy is not None else "none",
                persist=False,
            )
            query_text = promptops_result.prompt
        except Exception:
            query_text = query

    intent = parser.parse(query_text)
    time_window = intent.get("time_window")
    results = retrieval.search(query_text, time_window=time_window)
    on_query = system.config.get("processing", {}).get("on_query", {})
    allow_extract = bool(on_query.get("allow_decode_extract", False))
    require_idle = bool(on_query.get("require_idle", True))
    allow_ocr = bool(on_query.get("extractors", {}).get("ocr", True))
    allow_vlm = bool(on_query.get("extractors", {}).get("vlm", False))
    extracted_ids: list[str] = []
    if allow_extract and (allow_ocr or allow_vlm):
        can_run = True
        if require_idle:
            idle_window = float(system.config.get("runtime", {}).get("idle_window_s", 45))
            tracker = None
            try:
                tracker = system.get("tracking.input")
            except Exception:
                tracker = None
            if tracker is not None:
                try:
                    idle_seconds = float(tracker.idle_seconds())
                except Exception:
                    idle_seconds = 0.0
                can_run = idle_seconds >= idle_window
            else:
                assume_idle = bool(system.config.get("runtime", {}).get("activity", {}).get("assume_idle_when_missing", False))
                can_run = assume_idle
        if can_run:
            extract_on_demand(
                system,
                time_window,
                allow_ocr=allow_ocr,
                allow_vlm=allow_vlm,
                collected_ids=extracted_ids,
                candidate_ids=[result.get("record_id") for result in results if result.get("record_id")],
            )
            results = retrieval.search(query_text, time_window=time_window)

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
    if event_builder is not None:
        run_id = system.config.get("runtime", {}).get("run_id", "run")
        result_ids = [result.get("record_id") for result in results if result.get("record_id")]
        payload = {
            "event": "query.execute",
            "run_id": run_id,
            "query": query_text,
            "query_original": query,
            "time_window": time_window,
            "result_count": int(len(results)),
            "result_ids": result_ids,
            "extracted_count": int(len(extracted_ids)),
            "promptops_applied": bool(promptops_result and promptops_result.applied),
        }
        event_builder.ledger_entry(
            "query.execute",
            inputs=result_ids,
            outputs=extracted_ids,
            payload=payload,
        )
    return {"intent": intent, "results": results, "answer": answer_obj}
