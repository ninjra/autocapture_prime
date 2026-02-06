"""Query pipeline orchestration."""

from __future__ import annotations

import io
import zipfile
import time
from datetime import datetime, timezone
from typing import Any

from autocapture.core.hashing import hash_text, normalize_text
from autocapture_nx.kernel.derived_records import (
    build_derivation_edge,
    build_text_record,
    derivation_edge_id,
    extract_text_payload,
)
from autocapture_nx.kernel.frame_evidence import ensure_frame_evidence
from autocapture.indexing.factory import build_indexes
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.kernel.providers import capability_providers
from autocapture_nx.kernel.telemetry import record_telemetry
from autocapture_nx.state_layer.policy_gate import StatePolicyGate, normalize_state_policy_decision
from autocapture_nx.state_layer.evidence_compiler import EvidenceCompiler


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
    return capability_providers(capability, default_provider)


def _resolve_single_provider(capability: Any | None) -> Any | None:
    if capability is None:
        return None
    target = capability
    if hasattr(target, "target"):
        target = getattr(target, "target")
    if hasattr(target, "items"):
        try:
            items = list(target.items())
        except Exception:
            items = []
        if items:
            return items[0][1]
    return target


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
        blob = media.get(record_id)
        if not blob:
            continue
        frame = _extract_frame(blob, record)
        if not frame:
            continue

        record_id, record = ensure_frame_evidence(
            config=system.config if hasattr(system, "config") else {},
            metadata=metadata,
            media=media,
            record_id=record_id,
            record=record if isinstance(record, dict) else {},
            frame_bytes=frame,
            event_builder=event_builder,
            logger=None,
        )

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
                text = extract_text_payload(extractor.extract(frame))
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


def run_state_query(system, query: str) -> dict[str, Any]:
    start_perf = time.perf_counter()
    parser = system.get("time.intent_parser")
    retrieval = None
    evidence_compiler = None
    policy_gate = None
    if hasattr(system, "get"):
        try:
            retrieval = _resolve_single_provider(system.get("state.retrieval"))
        except Exception:
            retrieval = None
        try:
            evidence_compiler = _resolve_single_provider(system.get("state.evidence_compiler"))
        except Exception:
            evidence_compiler = None
        try:
            policy_gate = _resolve_single_provider(system.get("state.policy"))
        except Exception:
            policy_gate = None
    answer = system.get("answer.builder")
    metadata = system.get("storage.metadata")
    event_builder = None
    if hasattr(system, "get"):
        try:
            event_builder = system.get("event.builder")
        except Exception:
            event_builder = None

    query_text = query
    promptops_result = None
    promptops_cfg = system.config.get("promptops", {}) if hasattr(system, "config") else {}
    if isinstance(promptops_cfg, dict) and bool(promptops_cfg.get("enabled", True)):
        try:
            from autocapture.promptops.engine import PromptOpsLayer

            layer = PromptOpsLayer(system.config)
            strategy = promptops_cfg.get("query_strategy", "none")
            promptops_result = layer.prepare_prompt(
                query,
                prompt_id="state_query",
                strategy=str(strategy) if strategy is not None else "none",
                persist=False,
            )
            query_text = promptops_result.prompt
        except Exception:
            query_text = query

    if retrieval is None:
        try:
            from autocapture_nx.state_layer.retrieval import StateRetrieval
            from autocapture_nx.plugin_system.api import PluginContext

            ctx = PluginContext(
                config=system.config if hasattr(system, "config") else {},
                get_capability=system.get if hasattr(system, "get") else (lambda _name: None),
                logger=(getattr(system.get("observability.logger"), "log", lambda *_a, **_k: None) if hasattr(system, "get") else (lambda *_a, **_k: None)),
                rng=None,
                rng_seed=None,
                rng_seed_hex=None,
            )
            retrieval = StateRetrieval("state.retrieval.fallback", ctx)
        except Exception:
            retrieval = None

    if evidence_compiler is None:
        try:
            from autocapture_nx.plugin_system.api import PluginContext

            ctx = PluginContext(
                config=system.config if hasattr(system, "config") else {},
                get_capability=system.get if hasattr(system, "get") else (lambda _name: None),
                logger=(getattr(system.get("observability.logger"), "log", lambda *_a, **_k: None) if hasattr(system, "get") else (lambda *_a, **_k: None)),
                rng=None,
                rng_seed=None,
                rng_seed_hex=None,
            )
            evidence_compiler = EvidenceCompiler("state.evidence.compiler.fallback", ctx)
        except Exception:
            evidence_compiler = None

    if policy_gate is None:
        policy_gate = StatePolicyGate(system.config if hasattr(system, "config") else {})

    intent = parser.parse(query_text)
    time_window = intent.get("time_window")
    hits = retrieval.search(query_text, time_window=time_window) if retrieval is not None else []
    policy_decision = normalize_state_policy_decision(policy_gate.decide({"time_window": time_window}))
    if evidence_compiler is None:
        bundle = {
            "query_id": "state_query_error",
            "hits": [],
            "policy": {"can_show_raw_media": False, "can_export_text": False},
        }
    else:
        import json
        import hashlib

        seed = json.dumps({"query": query_text, "time_window": time_window}, sort_keys=True)
        query_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        bundle = evidence_compiler.compile(
            query_id=query_id,
            hits=hits,
            policy=policy_decision,
            metadata=metadata,
        )

    query_ledger_hash = None
    anchor_ref = None
    retrieval_trace = retrieval.trace() if retrieval is not None and hasattr(retrieval, "trace") else []
    if event_builder is not None:
        run_id = system.config.get("runtime", {}).get("run_id", "run")
        state_ids = [hit.get("state_id") for hit in hits if hit.get("state_id")]
        payload = {
            "event": "state.query.execute",
            "run_id": run_id,
            "query": query_text,
            "query_original": query,
            "time_window": time_window,
            "result_count": int(len(hits)),
            "state_ids": state_ids,
            "promptops_applied": bool(promptops_result and promptops_result.applied),
            "retrieval_trace": retrieval_trace,
        }
        query_ledger_hash = event_builder.ledger_entry(
            "state.query.execute",
            inputs=[],
            outputs=state_ids,
            payload=payload,
        )
        anchor_ref = event_builder.last_anchor() if hasattr(event_builder, "last_anchor") else None

    claims: list[dict[str, Any]] = []
    bundle_hits = bundle.get("hits") if isinstance(bundle.get("hits"), list) else []
    if policy_decision.can_export_text and bundle_hits:
        for hit in bundle_hits:
            if not isinstance(hit, dict):
                continue
            snippets = hit.get("extracted_text_snippets")
            if not isinstance(snippets, list):
                continue
            for snippet in snippets:
                if not isinstance(snippet, dict):
                    continue
                text = str(snippet.get("text", "")).strip()
                if not text:
                    continue
                media_id = str(snippet.get("media_id", ""))
                derived_id, derived_record = _derived_text_doc(hit, media_id, metadata)
                evidence_record = metadata.get(media_id, {}) if metadata is not None else {}
                evidence_hash = evidence_record.get("content_hash") or evidence_record.get("payload_hash")
                span_kind = "record"
                derived_hash = None
                if derived_record and derived_record.get("text"):
                    span_kind = "text"
                    derived_hash = derived_record.get("content_hash") or derived_record.get("payload_hash")
                if not query_ledger_hash or not anchor_ref or not evidence_hash:
                    continue
                offset_end = len(text) if span_kind == "text" else 0
                citations = [
                    {
                        "schema_version": 1,
                        "span_id": media_id,
                        "evidence_id": media_id,
                        "evidence_hash": evidence_hash,
                        "derived_id": derived_id,
                        "derived_hash": derived_hash,
                        "span_kind": span_kind,
                        "span_ref": derived_record.get("span_ref") if isinstance(derived_record, dict) else None,
                        "ledger_head": query_ledger_hash,
                        "anchor_ref": anchor_ref,
                        "source": "local",
                        "offset_start": 0,
                        "offset_end": offset_end,
                    }
                ]
                claims.append({"text": text, "citations": citations})

    if not claims and hits:
        for hit_item in hits:
            if not isinstance(hit_item, dict):
                continue
            evidence_list = hit_item.get("evidence", [])
            if not isinstance(evidence_list, list) or not evidence_list:
                continue
            ref = evidence_list[0] if isinstance(evidence_list[0], dict) else None
            if not ref:
                continue
            media_id = str(ref.get("media_id", ""))
            if not media_id:
                continue
            evidence_record = metadata.get(media_id, {}) if metadata is not None else {}
            evidence_hash = evidence_record.get("content_hash") or evidence_record.get("payload_hash")
            if not query_ledger_hash or not anchor_ref or not evidence_hash:
                continue
            summary = hit_item.get("summary_features", {}) if isinstance(hit_item.get("summary_features"), dict) else {}
            app = str(summary.get("app") or "unknown app")
            ts_start_ms = int(hit_item.get("ts_start_ms", 0) or 0)
            ts_end_ms = int(hit_item.get("ts_end_ms", 0) or 0)
            limitation = "summary-only (text export disabled)" if not policy_decision.can_export_text else "summary-only (text unavailable)"
            text = f"Observed activity in {app} between {ts_start_ms} and {ts_end_ms} ms ({limitation})."
            citations = [
                {
                    "schema_version": 1,
                    "span_id": media_id,
                    "evidence_id": media_id,
                    "evidence_hash": evidence_hash,
                    "derived_id": None,
                    "derived_hash": None,
                    "span_kind": "record",
                    "span_ref": None,
                    "ledger_head": query_ledger_hash,
                    "anchor_ref": anchor_ref,
                    "source": "local",
                    "offset_start": 0,
                    "offset_end": 0,
                }
            ]
            claims.append({"text": text, "citations": citations})

    try:
        answer_obj = answer.build(claims) if claims else {"state": "no_evidence", "claims": [], "errors": []}
    except Exception as exc:
        answer_obj = {
            "state": "error",
            "claims": [],
            "errors": [
                {
                    "error": "answer_builder_failed",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            ],
        }
    require_citations = bool(promptops_cfg.get("require_citations", True))
    if isinstance(answer_obj, dict):
        answer_obj = dict(answer_obj)
        answer_obj["policy"] = {"require_citations": require_citations}
        if claims and not policy_decision.can_export_text:
            answer_obj.setdefault("notice", "summary-only (text export disabled)")
        if require_citations and not answer_obj.get("claims"):
            answer_obj.setdefault("notice", "no evidence")

    elapsed_ms = (time.perf_counter() - start_perf) * 1000.0
    record_telemetry(
        "state.query",
        {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "latency_ms": float(round(elapsed_ms, 3)),
            "result_count": int(len(bundle.get("hits", []))),
        },
    )
    return {
        "intent": intent,
        "bundle": bundle,
        "answer": answer_obj,
        "processing": {
            "state_layer": {
                "query_enabled": True,
                "hits": int(len(bundle.get("hits", []))),
                "retrieval_trace": retrieval_trace,
            }
        },
    }


def _derived_text_doc(hit: dict[str, Any], media_id: str, metadata: Any) -> tuple[str | None, dict[str, Any] | None]:
    if metadata is None:
        return None, None
    provenance = hit.get("provenance", {}) if isinstance(hit.get("provenance"), dict) else {}
    input_ids = provenance.get("input_artifact_ids", []) if isinstance(provenance.get("input_artifact_ids"), list) else []
    for record_id in input_ids:
        record = metadata.get(record_id, {})
        if not isinstance(record, dict):
            continue
        if str(record.get("record_type")) != "derived.sst.state":
            continue
        screen_state_raw = record.get("screen_state")
        screen_state = screen_state_raw if isinstance(screen_state_raw, dict) else {}
        frame_id = str(screen_state.get("frame_id") or record.get("frame_id") or "")
        if frame_id != media_id:
            continue
        state_id = screen_state.get("state_id")
        run_id = record.get("run_id")
        if not state_id or not run_id:
            return None, None
        component = encode_record_id_component(str(state_id))
        doc_id = f"{run_id}/derived.sst.text/state/{component}"
        doc = metadata.get(doc_id, {})
        if isinstance(doc, dict):
            return doc_id, doc
    return None, None


def run_query_without_state(system, query: str) -> dict[str, Any]:
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
    try:
        answer_obj = answer.build(claims)
    except Exception as exc:
        answer_obj = {
            "state": "error",
            "claims": [],
            "errors": [
                {
                    "error": "answer_builder_failed",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            ],
        }
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


def _should_fallback_state(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return True
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    state = str(answer.get("state", ""))
    if state in ("no_evidence", "error"):
        return True
    bundle = result.get("bundle", {}) if isinstance(result.get("bundle", {}), dict) else {}
    hits = bundle.get("hits", []) if isinstance(bundle.get("hits", []), list) else []
    return not hits


def _merge_state_fallback(state_result: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(fallback)
    processing = merged.get("processing", {}) if isinstance(merged.get("processing", {}), dict) else {}
    processing["state_fallback"] = {
        "used": True,
        "state_answer": state_result.get("answer"),
        "state_processing": state_result.get("processing"),
    }
    merged["processing"] = processing
    return merged


def run_query(system, query: str) -> dict[str, Any]:
    state_cfg = system.config.get("processing", {}).get("state_layer", {}) if hasattr(system, "config") else {}
    if isinstance(state_cfg, dict) and bool(state_cfg.get("query_enabled", False)):
        state_result = run_state_query(system, query)
        if _should_fallback_state(state_result):
            fallback = run_query_without_state(system, query)
            return _merge_state_fallback(state_result, fallback)
        return state_result
    return run_query_without_state(system, query)
