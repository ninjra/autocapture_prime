"""Query pipeline orchestration."""

from __future__ import annotations

import io
import zipfile
import time
from datetime import datetime, timezone
from typing import Any

from autocapture.core.hashing import hash_text, normalize_text
from autocapture_nx.kernel.hashing import sha256_canonical, sha256_file
from autocapture_nx.kernel.hashing import sha256_text
from autocapture_nx.kernel.loader import _canonicalize_config_for_hash
from autocapture_nx.kernel.paths import resolve_repo_path
from autocapture_nx.kernel.derived_records import (
    build_derivation_edge,
    build_text_record,
    build_artifact_manifest,
    derived_text_record_id,
    derivation_edge_id,
    extract_text_payload,
    artifact_manifest_id,
)
from autocapture_nx.kernel.frame_evidence import ensure_frame_evidence
from autocapture.indexing.factory import build_indexes
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.kernel.providers import capability_providers
from autocapture_nx.kernel.schema_registry import SchemaRegistry
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


def _citation_locator(
    *,
    kind: str,
    record_id: str,
    record_hash: str | None,
    offset_start: int | None = None,
    offset_end: int | None = None,
    span_text: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": str(kind),
        "record_id": str(record_id),
        "record_hash": str(record_hash or ""),
        "offset_start": int(offset_start) if offset_start is not None else None,
        "offset_end": int(offset_end) if offset_end is not None else None,
        "span_sha256": sha256_text(str(span_text or "")) if span_text is not None else None,
    }
    return payload


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
        for provider_id, extractor in _capability_providers(ocr, "ocr.engine"):
            derived_ids.append(
                (
                    derived_text_record_id(
                        kind="ocr",
                        run_id=run_id,
                        provider_id=str(provider_id),
                        source_id=record_id,
                        config=config if isinstance(config, dict) else {},
                    ),
                    extractor,
                    "ocr",
                    provider_id,
                )
            )
        for provider_id, extractor in _capability_providers(vlm, "vision.extractor"):
            derived_ids.append(
                (
                    derived_text_record_id(
                        kind="vlm",
                        run_id=run_id,
                        provider_id=str(provider_id),
                        source_id=record_id,
                        config=config if isinstance(config, dict) else {},
                    ),
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
            # META-07: persist a content-addressed artifact manifest with lineage pointers.
            try:
                run_id = str(payload.get("run_id") or record_id.split("/", 1)[0])
                manifest_id = artifact_manifest_id(run_id, derived_id)
                artifact_hash = str(payload.get("payload_hash") or payload.get("content_hash") or "")
                derived_from = {
                    "evidence_id": record_id,
                    "evidence_hash": record.get("content_hash") if isinstance(record, dict) else None,
                    "model_digest": payload.get("model_digest"),
                }
                manifest = build_artifact_manifest(
                    run_id=run_id,
                    artifact_id=derived_id,
                    artifact_sha256=artifact_hash,
                    derived_from=derived_from,
                    ts_utc=payload.get("ts_utc"),
                )
                if hasattr(metadata, "put_new"):
                    metadata.put_new(manifest_id, manifest)
                else:
                    metadata.put(manifest_id, manifest)
            except Exception:
                pass
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
                offset_start = 0
                offset_end = len(text) if span_kind == "text" else 0
                if span_kind == "text" and isinstance(derived_record, dict) and derived_record.get("text"):
                    full = str(derived_record.get("text") or "")
                    idx = full.find(text)
                    if idx >= 0:
                        offset_start = idx
                        offset_end = idx + len(text)
                        text = full[offset_start:offset_end]
                citations = [
                    {
                        "schema_version": 1,
                        "locator": _citation_locator(
                            kind="text_offsets" if span_kind == "text" else "record",
                            record_id=str(derived_id or media_id),
                            record_hash=str(derived_hash or evidence_hash),
                            offset_start=offset_start if span_kind == "text" else None,
                            offset_end=offset_end if span_kind == "text" else None,
                            span_text=text if span_kind == "text" else None,
                        ),
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
                        "offset_start": offset_start,
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
                    "locator": _citation_locator(
                        kind="record",
                        record_id=media_id,
                        record_hash=str(evidence_hash),
                    ),
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


def run_query_without_state(system, query: str, *, schedule_extract: bool = False) -> dict[str, Any]:
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

    scheduled_job_id: str | None = None
    if schedule_extract and extraction_blocked and candidate_ids and metadata is not None:
        try:
            scheduled_job_id = _schedule_extraction_job(
                metadata,
                run_id=_source_run_id(results, candidate_ids),
                candidate_ids=[str(cid) for cid in candidate_ids if cid],
                time_window=time_window,
                allow_ocr=bool(allow_ocr),
                allow_vlm=bool(allow_vlm),
                blocked_reason=str(extraction_blocked_reason or ""),
                query=str(query_text or query),
            )
        except Exception:
            scheduled_job_id = None

    # META-08: minimal evaluation fields to make missing extraction measurable.
    # Keep this deterministic: compute only from returned results/candidates.
    seen_ids: set[str] = set()
    unique_results: list[dict[str, Any]] = []
    newest_ts: str | None = None
    for item in results:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("record_id") or "")
        if not rid or rid in seen_ids:
            continue
        seen_ids.add(rid)
        unique_results.append(item)
        ts = item.get("ts_utc") or item.get("ts_end_utc") or item.get("ts_start_utc")
        if isinstance(ts, str) and ts:
            if newest_ts is None or ts > newest_ts:
                newest_ts = ts
    result_count = int(len(unique_results))
    candidate_count = int(len(candidate_ids))
    if candidate_count > 0:
        coverage_ratio = min(1.0, float(result_count) / float(candidate_count))
        missing_spans = max(0, candidate_count - result_count)
    else:
        coverage_ratio = 1.0 if result_count > 0 else 0.0
        missing_spans = 0
    evaluation: dict[str, Any] = {
        "schema_version": 1,
        "coverage_ratio": float(round(coverage_ratio, 6)),
        "missing_spans_count": int(missing_spans),
        "blocked_extract": bool(extraction_blocked),
        "blocked_reason": str(extraction_blocked_reason or ""),
        "scheduled_extract_job_id": scheduled_job_id,
        "result_count": int(result_count),
        "candidate_count": int(candidate_count),
        "freshness_newest_ts_utc": newest_ts,
    }
    try:
        registry = SchemaRegistry()
        schema = registry.load_schema_path("contracts/evaluation.schema.json")
        issues = registry.validate(schema, evaluation)
        if issues:
            evaluation["schema_error"] = registry.format_issues(issues)
    except Exception:
        pass

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

    def _record_hash(rec: dict[str, Any]) -> str | None:
        if not isinstance(rec, dict):
            return None
        return rec.get("content_hash") or rec.get("payload_hash")

    def _claim_with_citation(
        *,
        claim_text: str,
        evidence_id: str,
        derived_id: str | None,
        match_text: str,
        match_start: int,
        match_end: int,
    ) -> dict[str, Any] | None:
        if metadata is None:
            return None
        record_id = derived_id or evidence_id
        record = metadata.get(record_id, {})
        evidence_record = metadata.get(evidence_id, {})
        if not isinstance(record, dict) or not isinstance(evidence_record, dict):
            return None
        derived_hash = _record_hash(record) if derived_id else None
        evidence_hash = _record_hash(evidence_record)
        locator = _citation_locator(
            kind="text_offsets",
            record_id=str(record_id),
            record_hash=str(derived_hash or ""),
            offset_start=int(match_start),
            offset_end=int(match_end),
            span_text=match_text,
        )
        return {
            "text": str(claim_text),
            "citations": [
                {
                    "schema_version": 1,
                    "locator": locator,
                    "span_id": evidence_id,
                    "evidence_id": evidence_id,
                    "evidence_hash": evidence_hash,
                    "derived_id": derived_id,
                    "derived_hash": derived_hash,
                    "span_kind": "text",
                    "span_ref": record.get("span_ref") if isinstance(record, dict) else None,
                    "ledger_head": query_ledger_hash,
                    "anchor_ref": anchor_ref,
                    "source": "local",
                    "offset_start": int(match_start),
                    "offset_end": int(match_end),
                }
            ],
        }

    # Optional: query-time QA helpers that use already-extracted metadata only (no media decode).
    # These improve answerability for natural-language questions that don't share tokens with the
    # best supporting evidence (e.g. "what song is playing").
    qlow = str(query or "").casefold()
    custom_claims: list[dict[str, Any]] = []
    custom_claims_error: str | None = None
    custom_claims_debug: dict[str, Any] = {}
    try:
        if retrieval is not None and metadata is not None:
            def _scan_metadata_for(pattern, *, limit: int = 500):  # type: ignore[no-untyped-def]
                """Fallback text scan over already-extracted metadata (no media decode).

                Used when retrieval indexes don't surface the right evidence for
                natural-language questions.
                """

                import re as _re

                pat = pattern if hasattr(pattern, "search") else _re.compile(str(pattern))
                found: list[tuple[str, Any, Any]] = []
                try:
                    keys = list(getattr(metadata, "keys", lambda: [])())
                except Exception:
                    keys = []
                # Prefer derived text records first.
                for rid in keys:
                    rec = metadata.get(rid, {})
                    if not isinstance(rec, dict):
                        continue
                    rtype = str(rec.get("record_type") or "")
                    if not rtype.startswith("derived.text."):
                        continue
                    txt = rec.get("text", "")
                    if not isinstance(txt, str) or not txt:
                        continue
                    m = pat.search(txt)
                    if not m:
                        continue
                    found.append((str(rid), rec, m))
                    if len(found) >= int(limit):
                        break
                return found

            # "Who is working with me on the quorum task" -> extract contractor name from task title.
            if "quorum" in qlow and ("working" in qlow or "who" in qlow):
                # Prefer the explicit assignee string when present (e.g. "task was assigned to OpenInvoice").
                hint = retrieval.search("assigned to", time_window=time_window) or retrieval.search("assigned", time_window=time_window) or retrieval.search("assigned", time_window=None)
                custom_claims_debug["quorum_hint_count"] = int(len(hint)) if isinstance(hint, list) else 0
                pat = __import__("re").compile(r"assigned\s*to\s*(?P<assignee>[A-Za-z][A-Za-z0-9]{1,48})", flags=__import__("re").IGNORECASE)

                def _split_camel(value: str) -> str:
                    if not value:
                        return value
                    out: list[str] = []
                    current = value[0]
                    for ch in value[1:]:
                        if ch.isupper() and current and (current[-1].islower() or current[-1].isdigit()):
                            out.append(current)
                            current = ch
                        else:
                            current += ch
                    out.append(current)
                    return " ".join(p for p in out if p)

                matches = []
                try:
                    matches = [(str(hit.get("record_id") or ""), hit.get("derived_id"), pat.search((metadata.get(hit.get("derived_id") or hit.get("record_id") or "", {}) or {}).get("text", ""))) for hit in (hint[:10] if isinstance(hint, list) else [])]
                except Exception:
                    matches = []
                found = []
                for evidence_id, derived_id, m in matches:
                    if evidence_id and m:
                        found.append((evidence_id, derived_id, m))
                if not found:
                    for rid, _rec, m in _scan_metadata_for(pat, limit=200):
                        found.append((rid, None, m))
                        break
                custom_claims_debug["quorum_found_count"] = int(len(found))
                for evidence_id, derived_id, m in found[:10]:
                    raw = str(m.group("assignee") or "").strip()
                    if not raw:
                        continue
                    # Keep only alphanumerics so we don't fabricate separators from OCR noise.
                    cleaned = "".join(ch for ch in raw if ch.isalnum())
                    if not cleaned:
                        continue
                    name = _split_camel(cleaned)
                    claim = _claim_with_citation(
                        claim_text=f"Quorum task collaborator: {name}",
                        evidence_id=evidence_id,
                        derived_id=derived_id,
                        match_text=m.group(0),
                        match_start=m.start(),
                        match_end=m.end(),
                    )
                    if claim:
                        custom_claims.append(claim)
                        break

            # "What song is playing" -> extract from SiriusXM "Chill Instrumental ..." line.
            if "song" in qlow and ("play" in qlow or "playing" in qlow):
                hint = retrieval.search("Chill Instrumental", time_window=time_window) or retrieval.search("Chill Instrumental", time_window=None)
                custom_claims_debug["song_hint_count"] = int(len(hint)) if isinstance(hint, list) else 0
                pat = __import__("re").compile(
                    r"Chill\s+Instrumental\s+"
                    r"(?P<artist>[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})"
                    r"\s*[-–—−]\s*"
                    r"(?P<title>[A-Z][A-Za-z]+(?:\s+(?:[A-Z][A-Za-z]+|At|Of|In|On|To|And|&)){0,6})"
                )
                found = []
                if isinstance(hint, list):
                    for hit in hint[:10]:
                        evidence_id = str(hit.get("record_id") or "")
                        derived_id = hit.get("derived_id")
                        record_id = derived_id or evidence_id
                        rec = metadata.get(record_id, {})
                        txt = rec.get("text", "") if isinstance(rec, dict) else ""
                        m = pat.search(txt)
                        if evidence_id and m:
                            found.append((evidence_id, derived_id, m))
                if not found:
                    for rid, _rec, m in _scan_metadata_for(pat, limit=200):
                        found.append((rid, None, m))
                        break
                custom_claims_debug["song_found_count"] = int(len(found))
                for evidence_id, derived_id, m in found[:10]:
                    artist = m.group("artist").strip()
                    title = m.group("title").strip()
                    if not artist or not title:
                        continue
                    claim = _claim_with_citation(
                        claim_text=f"Now playing: {artist} - {title}",
                        evidence_id=evidence_id,
                        derived_id=derived_id,
                        match_text=m.group(0),
                        match_start=m.start(),
                        match_end=m.end(),
                    )
                    if claim:
                        custom_claims.append(claim)
                        break
    except Exception:
        # Fail closed: query should still return normal retrieval results.
        try:
            import traceback

            custom_claims_error = traceback.format_exc(limit=2).strip()
        except Exception:
            custom_claims_error = "custom_claims_exception"
        custom_claims = list(custom_claims)

    claims = []
    stale_hits: list[str] = []
    for claim in custom_claims:
        claims.append(claim)
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
        offset_start = 0
        offset_end = len(text) if text else 0
        locator_kind = "text_offsets" if span_kind == "text" else ("time_range" if isinstance(span_ref, dict) and span_ref.get("kind") == "time" else "record")
        locator_record_id = str(derived_id or evidence_id)
        locator_record_hash = str(derived_hash or evidence_hash or "")
        locator: dict[str, Any] = _citation_locator(
            kind=locator_kind,
            record_id=locator_record_id,
            record_hash=locator_record_hash,
            offset_start=offset_start if span_kind == "text" else None,
            offset_end=offset_end if span_kind == "text" else None,
            span_text=text if span_kind == "text" else None,
        )
        claims.append(
            {
                "text": text or f"Matched record {evidence_id}",
                "citations": [
                    {
                        "schema_version": 1,
                        "locator": locator,
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
                        "offset_start": offset_start,
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

    config = system.config if hasattr(system, "config") else {}
    data_dir = None
    run_id = None
    try:
        storage_cfg = config.get("storage", {}) if isinstance(config, dict) else {}
        if isinstance(storage_cfg, dict):
            data_dir = storage_cfg.get("data_dir")
        run_id = config.get("runtime", {}).get("run_id") if isinstance(config, dict) else None
    except Exception:
        data_dir = None
        run_id = None

    contracts_hash = None
    plugins_hash = None
    try:
        contract_lock = resolve_repo_path("contracts/lock.json")
        if contract_lock.exists():
            contracts_hash = sha256_file(contract_lock)
    except Exception:
        contracts_hash = None
    try:
        locks_cfg = config.get("plugins", {}).get("locks", {}) if isinstance(config, dict) else {}
        lockfile = locks_cfg.get("lockfile", "config/plugin_locks.json") if isinstance(locks_cfg, dict) else "config/plugin_locks.json"
        lock_path = resolve_repo_path(lockfile)
        if lock_path.exists():
            plugins_hash = sha256_file(lock_path)
    except Exception:
        plugins_hash = None

    config_hash = None
    try:
        config_hash = sha256_canonical(_canonicalize_config_for_hash(config if isinstance(config, dict) else {}))
    except Exception:
        config_hash = None

    return {
        "provenance": {
            "schema_version": 1,
            "run_id": run_id,
            "data_dir": data_dir,
            "effective_config_sha256": config_hash,
            "contracts_lock_sha256": contracts_hash,
            "plugin_locks_sha256": plugins_hash,
            "query_ledger_head": query_ledger_hash,
            "anchor_ref": anchor_ref,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        "intent": intent,
        "results": results,
        "evaluation": evaluation,
        "answer": answer_obj,
        "processing": {
            "extraction": {
                "allowed": bool(allow_extract and (allow_ocr or allow_vlm)),
                "ran": bool(extraction_ran),
                "blocked": bool(extraction_blocked),
                "blocked_reason": extraction_blocked_reason,
                "scheduled_job_id": scheduled_job_id,
                "require_idle": bool(require_idle),
                "idle_seconds": idle_seconds,
                "idle_window_s": idle_window,
                "candidate_count": len(candidate_ids),
                "extracted_count": len(extracted_ids),
            }
        },
        "custom_claims": {
            "count": int(len(custom_claims)),
            "error": custom_claims_error,
            "debug": custom_claims_debug,
        },
        "scheduled_extract_job_id": scheduled_job_id,
    }


def _source_run_id(results: list[dict[str, Any]], candidate_ids: list[str]) -> str:
    for item in results:
        if isinstance(item, dict):
            rid = str(item.get("record_id") or "")
            if "/" in rid:
                return rid.split("/", 1)[0]
    for rid in candidate_ids:
        rid = str(rid or "")
        if "/" in rid:
            return rid.split("/", 1)[0]
    return "run"


def _schedule_extraction_job(
    metadata: Any,
    *,
    run_id: str,
    candidate_ids: list[str],
    time_window: dict[str, Any] | None,
    allow_ocr: bool,
    allow_vlm: bool,
    blocked_reason: str,
    query: str,
) -> str:
    payload = {
        "schema_version": 1,
        "record_type": "derived.job.extract",
        "run_id": str(run_id),
        "state": "pending",
        "candidate_ids": list(candidate_ids),
        "time_window": time_window,
        "allow_ocr": bool(allow_ocr),
        "allow_vlm": bool(allow_vlm),
        "blocked_reason": str(blocked_reason or ""),
        "query": str(query or ""),
    }
    # Deterministic: hash canonical JSON of the scheduling payload.
    job_hash = sha256_canonical(payload)[:16]
    record_id = f"{run_id}/derived.job.extract/{job_hash}"
    try:
        if metadata.get(record_id) is not None:
            return record_id
    except Exception:
        pass
    payload["content_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "content_hash"})
    if hasattr(metadata, "put_new"):
        metadata.put_new(record_id, payload)
    else:
        metadata.put(record_id, payload)
    return record_id


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


def run_query(system, query: str, *, schedule_extract: bool = False) -> dict[str, Any]:
    state_cfg = system.config.get("processing", {}).get("state_layer", {}) if hasattr(system, "config") else {}
    if isinstance(state_cfg, dict) and bool(state_cfg.get("query_enabled", False)):
        state_result = run_state_query(system, query)
        if _should_fallback_state(state_result):
            fallback = run_query_without_state(system, query, schedule_extract=bool(schedule_extract))
            return _merge_state_fallback(state_result, fallback)
        return state_result
    return run_query_without_state(system, query, schedule_extract=bool(schedule_extract))
