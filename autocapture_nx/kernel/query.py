"""Query pipeline orchestration."""

from __future__ import annotations

import io
import zipfile
import time
from datetime import datetime, timezone
from typing import Any

from autocapture.core.hashing import hash_text, normalize_text
from autocapture_nx.kernel.derived_records import build_derivation_edge, build_text_record, derivation_edge_id
from autocapture.indexing.factory import build_indexes
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.kernel.telemetry import record_telemetry


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


def _ts_value(ts: str | None) -> float:
    parsed = _parse_ts(ts)
    if parsed is None:
        return 0.0
    return float(parsed.timestamp())


def _evidence_candidates(metadata: Any, time_window: dict[str, Any] | None, limit: int) -> list[str]:
    evidence: list[tuple[float, str]] = []
    for record_id in getattr(metadata, "keys", lambda: [])():
        record = metadata.get(record_id, {})
        record_type = str(record.get("record_type", ""))
        if not record_type.startswith("evidence.capture."):
            continue
        ts = record.get("ts_start_utc") or record.get("ts_utc")
        if not _within_window(ts, time_window):
            continue
        evidence.append((_ts_value(ts), str(record_id)))
    evidence.sort(key=lambda item: (-item[0], item[1]))
    return [record_id for _ts, record_id in evidence[: max(0, int(limit))]]


def _capability_providers(capability: Any | None, default_provider: str) -> list[tuple[str, Any]]:
    if capability is None:
        return []
    target = capability
    if hasattr(target, "target"):
        target = getattr(target, "target")
    if hasattr(target, "items"):
        try:
            items = target.items()
            if items:
                return list(items)
        except Exception:
            pass
    return [(default_provider, capability)]


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
    pipeline = None
    if hasattr(system, "has") and system.has("processing.pipeline"):
        try:
            pipeline = system.get("processing.pipeline")
        except Exception:
            pipeline = None
    event_builder = None
    if hasattr(system, "get"):
        try:
            event_builder = system.get("event.builder")
        except Exception:
            event_builder = None

    config = None
    if hasattr(system, "config"):
        config = system.config
    elif isinstance(system, dict):
        config = system.get("config")
    lexical = None
    vector = None
    if isinstance(config, dict) and config:
        try:
            lexical, vector = build_indexes(config)
        except Exception:
            lexical = None
            vector = None
    sst_cfg = config.get("processing", {}).get("sst", {}) if isinstance(config, dict) else {}
    pipeline_enabled = bool(sst_cfg.get("enabled", True)) and pipeline is not None
    max_seconds = int(config.get("processing", {}).get("idle", {}).get("max_seconds_per_run", 30)) if isinstance(config, dict) else 30
    deadline = time.time() + max(1, max_seconds)

    def _index_text(doc_id: str, text: str) -> None:
        if not text:
            return
        if lexical is not None:
            try:
                lexical.index(doc_id, text)
            except Exception:
                pass
        if vector is not None:
            try:
                vector.index(doc_id, text)
            except Exception:
                pass

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
        derived_ids: list[tuple[str, Any, str, str]] = []
        encoded_source = encode_record_id_component(record_id)
        for provider_id, extractor in _capability_providers(ocr, "ocr.engine"):
            provider_component = encode_record_id_component(provider_id)
            derived_ids.append(
                (
                    f"{run_id}/derived.text.ocr/{provider_component}/{encoded_source}",
                    extractor,
                    "ocr",
                    provider_id,
                )
            )
        for provider_id, extractor in _capability_providers(vlm, "vision.extractor"):
            provider_component = encode_record_id_component(provider_id)
            derived_ids.append(
                (
                    f"{run_id}/derived.text.vlm/{provider_component}/{encoded_source}",
                    extractor,
                    "vlm",
                    provider_id,
                )
            )
        if not derived_ids:
            continue
        blob = media.get(record_id)
        if not blob:
            continue
        frame = _extract_frame(blob, record)
        if not frame:
            continue
        if pipeline_enabled and pipeline is not None and hasattr(pipeline, "process_record"):
            try:
                result = pipeline.process_record(
                    record_id=record_id,
                    record=record,
                    frame_bytes=frame,
                    allow_ocr=allow_ocr,
                    allow_vlm=allow_vlm,
                    should_abort=None,
                    deadline_ts=deadline,
                )
            except Exception:
                continue
            if collected_ids is not None:
                collected_ids.extend(result.derived_ids)
            processed += int(result.derived_records)
            if processed >= limit or time.time() >= deadline:
                break
            continue
        for derived_id, extractor, kind, provider_id in derived_ids:
            if metadata.get(derived_id):
                continue
            try:
                text = extractor.extract(frame).get("text", "")
            except Exception:
                continue
            payload = build_text_record(
                kind=kind,
                text=text,
                source_id=record_id,
                source_record=record,
                provider_id=provider_id,
                config=system.config if hasattr(system, "config") else {},
                ts_utc=record.get("ts_utc"),
            )
            if not payload:
                continue
            if hasattr(metadata, "put_new"):
                try:
                    metadata.put_new(derived_id, payload)
                except Exception:
                    continue
            else:
                metadata.put(derived_id, payload)
            _index_text(derived_id, payload.get("text", ""))
            if collected_ids is not None:
                collected_ids.append(derived_id)
            edge_id = None
            try:
                run_id = payload.get("run_id") or record_id.split("/", 1)[0]
                edge_id = derivation_edge_id(run_id, record_id, derived_id)
                edge_payload = build_derivation_edge(
                    run_id=run_id,
                    parent_id=record_id,
                    child_id=derived_id,
                    relation_type="derived_from",
                    span_ref=payload.get("span_ref", {}),
                    method=kind,
                )
                if hasattr(metadata, "put_new"):
                    try:
                        metadata.put_new(edge_id, edge_payload)
                    except Exception:
                        edge_id = None
                else:
                    metadata.put(edge_id, edge_payload)
            except Exception:
                edge_id = None
            if event_builder is not None:
                event_payload = dict(payload)
                event_payload["derived_id"] = derived_id
                if edge_id:
                    event_payload["derivation_edge_id"] = edge_id
                parent_hash = record.get("content_hash")
                if parent_hash:
                    event_payload["parent_content_hash"] = parent_hash
                event_builder.journal_event("derived.extract", event_payload, event_id=derived_id, ts_utc=payload.get("ts_utc"))
                event_builder.ledger_entry(
                    "derived.extract",
                    inputs=[record_id],
                    outputs=[derived_id] + ([edge_id] if edge_id else []),
                    payload=event_payload,
                    entry_id=derived_id,
                    ts_utc=payload.get("ts_utc"),
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
    start_perf = time.perf_counter()
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
    metadata = system.get("storage.metadata")
    stale_map: dict[str, str] = {}
    try:
        stale_cap = system.get("integrity.stale")
    except Exception:
        stale_cap = None
    if stale_cap is not None and hasattr(stale_cap, "target"):
        stale_cap = getattr(stale_cap, "target")
    if isinstance(stale_cap, dict):
        stale_map = dict(stale_cap)
    results = retrieval.search(query_text, time_window=time_window)
    on_query = system.config.get("processing", {}).get("on_query", {})
    allow_extract = bool(on_query.get("allow_decode_extract", False))
    require_idle = bool(on_query.get("require_idle", True))
    allow_ocr = bool(on_query.get("extractors", {}).get("ocr", True))
    allow_vlm = bool(on_query.get("extractors", {}).get("vlm", False))
    extracted_ids: list[str] = []
    extraction_ran = False
    extraction_blocked = False
    extraction_blocked_reason: str | None = None
    idle_seconds: float | None = None
    idle_window = None
    candidate_limit = int(on_query.get("candidate_limit", 10))
    candidate_ids = [result.get("record_id") for result in results if result.get("record_id")]
    if not candidate_ids and metadata is not None:
        candidate_ids = _evidence_candidates(metadata, time_window, candidate_limit)
    candidate_ids = [cid for cid in candidate_ids if cid]
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
                if not assume_idle:
                    extraction_blocked = True
                    extraction_blocked_reason = "idle_required"
        if can_run and candidate_ids:
            extract_on_demand(
                system,
                time_window,
                allow_ocr=allow_ocr,
                allow_vlm=allow_vlm,
                collected_ids=extracted_ids,
                candidate_ids=candidate_ids,
            )
            extraction_ran = True
            results = retrieval.search(query_text, time_window=time_window)
        elif not candidate_ids:
            extraction_blocked = True
            extraction_blocked_reason = "no_candidates"
        elif not can_run:
            extraction_blocked = True
            if idle_seconds is not None and idle_window is not None and idle_seconds < idle_window:
                extraction_blocked_reason = "user_active"
            elif extraction_blocked_reason is None:
                extraction_blocked_reason = "idle_required"
    else:
        extraction_blocked = True
        extraction_blocked_reason = "disabled"

    query_ledger_hash = None
    anchor_ref = None
    retrieval_trace = retrieval.trace() if hasattr(retrieval, "trace") else []
    if event_builder is not None:
        run_id = system.config.get("runtime", {}).get("run_id", "run")
        result_ids = [result.get("record_id") for result in results if result.get("record_id")]
        result_refs = [
            {"evidence_id": result.get("record_id"), "derived_id": result.get("derived_id")}
            for result in results
            if result.get("record_id")
        ]
        payload = {
            "event": "query.execute",
            "run_id": run_id,
            "query": query_text,
            "query_original": query,
            "time_window": time_window,
            "result_count": int(len(results)),
            "result_ids": result_ids,
            "result_refs": result_refs,
            "extracted_count": int(len(extracted_ids)),
            "candidate_ids": candidate_ids,
            "candidate_limit": int(candidate_limit),
            "extraction_ran": bool(extraction_ran),
            "extraction_allowed": bool(allow_extract),
            "promptops_applied": bool(promptops_result and promptops_result.applied),
            "retrieval_trace": retrieval_trace,
        }
        query_ledger_hash = event_builder.ledger_entry(
            "query.execute",
            inputs=[cid for cid in candidate_ids if cid],
            outputs=result_ids + list(extracted_ids),
            payload=payload,
        )
        anchor_ref = event_builder.last_anchor() if hasattr(event_builder, "last_anchor") else None

    claims = []
    stale_hits: list[str] = []
    for result in results:
        derived_id = result.get("derived_id")
        evidence_id = result["record_id"]
        stale_reason = stale_map.get(evidence_id)
        if stale_reason:
            result["stale"] = True
            result["stale_reason"] = stale_reason
            stale_hits.append(evidence_id)
        record = metadata.get(derived_id or evidence_id, {})
        evidence_record = metadata.get(evidence_id, {})
        text = record.get("text", "")
        evidence_hash = evidence_record.get("content_hash") or evidence_record.get("payload_hash")
        if evidence_hash is None and evidence_record.get("text"):
            evidence_hash = hash_text(normalize_text(evidence_record.get("text", "")))
        derived_hash = None
        span_ref = record.get("span_ref") if isinstance(record, dict) else None
        if derived_id:
            derived_record = metadata.get(derived_id, {})
            derived_hash = derived_record.get("content_hash") or derived_record.get("payload_hash")
            if derived_hash is None and derived_record.get("text"):
                derived_hash = hash_text(normalize_text(derived_record.get("text", "")))
        span_kind = "text" if text else "record"
        offset_end = len(text) if text else 0
        claims.append(
            {
                "text": text or f"Matched record {evidence_id}",
                "citations": [
                    {
                        "schema_version": 1,
                        "span_id": evidence_id,
                        "evidence_id": evidence_id,
                        "evidence_hash": evidence_hash,
                        "derived_id": derived_id,
                        "derived_hash": derived_hash,
                        "span_kind": span_kind,
                        "span_ref": span_ref,
                        "ledger_head": query_ledger_hash,
                        "anchor_ref": anchor_ref,
                        "source": "local",
                        "offset_start": 0,
                        "offset_end": offset_end,
                        "stale": bool(stale_reason),
                        "stale_reason": stale_reason,
                    }
                ],
            }
        )
    answer_obj = answer.build(claims)
    require_citations = bool(promptops_cfg.get("require_citations", True))
    if isinstance(answer_obj, dict):
        answer_obj = dict(answer_obj)
        answer_obj["policy"] = {"require_citations": require_citations}
        if require_citations:
            if not answer_obj.get("claims"):
                answer_obj.setdefault(
                    "notice",
                    "Citations required: no evidence available for this query yet.",
                )
            elif answer_obj.get("state") == "partial":
                answer_obj.setdefault(
                    "notice",
                    "Some claims were omitted because citations could not be verified.",
                )
        if stale_hits:
            answer_obj["stale"] = True
            answer_obj["stale_evidence"] = sorted(set(stale_hits))
    elapsed_ms = (time.perf_counter() - start_perf) * 1000.0
    record_telemetry(
        "query",
        {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "latency_ms": float(round(elapsed_ms, 3)),
            "result_count": int(len(results)),
            "extraction_ran": bool(extraction_ran),
            "extraction_blocked": bool(extraction_blocked),
            "blocked_reason": extraction_blocked_reason or "",
        },
    )
    return {
        "intent": intent,
        "results": results,
        "answer": answer_obj,
        "processing": {
            "extraction": {
                "allowed": bool(allow_extract and (allow_ocr or allow_vlm)),
                "ran": bool(extraction_ran),
                "blocked": bool(extraction_blocked),
                "blocked_reason": extraction_blocked_reason,
                "require_idle": bool(require_idle),
                "idle_seconds": idle_seconds,
                "idle_window_s": idle_window,
                "candidate_count": len(candidate_ids),
                "extracted_count": len(extracted_ids),
            }
        },
    }
