"""Query pipeline orchestration."""

from __future__ import annotations

import io
import zipfile
import time
import sqlite3
import re
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
from autocapture_nx.storage.facts_ndjson import append_fact_line
from autocapture_nx.state_layer.policy_gate import StatePolicyGate, normalize_state_policy_decision
from autocapture_nx.state_layer.evidence_compiler import EvidenceCompiler
from autocapture_nx.kernel.activity_signal import load_activity_signal


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
    max_limit = max(0, int(limit))
    if max_limit <= 0:
        return []
    evidence: list[tuple[float, str]] = []
    if hasattr(metadata, "latest"):
        try:
            per_type_limit = max(50, max_limit * 5)
            for record_type in (
                "evidence.capture.frame",
                "evidence.capture.image",
                "evidence.capture.video",
                "evidence.capture.audio",
            ):
                for item in metadata.latest(record_type=record_type, limit=per_type_limit):
                    if not isinstance(item, dict):
                        continue
                    record_id = str(item.get("record_id") or "")
                    record = item.get("record")
                    if not record_id or not isinstance(record, dict):
                        continue
                    ts = record.get("ts_start_utc") or record.get("ts_utc")
                    if not _within_window(ts, time_window):
                        continue
                    evidence.append((_ts_value(ts), record_id))
            if evidence:
                evidence.sort(key=lambda item: (-item[0], item[1]))
                dedup: list[str] = []
                seen: set[str] = set()
                for _ts, rid in evidence:
                    if rid in seen:
                        continue
                    seen.add(rid)
                    dedup.append(rid)
                    if len(dedup) >= max_limit:
                        break
                return dedup
        except Exception:
            pass

    max_scan = max(500, max_limit * 50)
    for idx, record_id in enumerate(getattr(metadata, "keys", lambda: [])()):
        if idx >= max_scan:
            break
        try:
            record = metadata.get(record_id, {})
        except Exception:
            continue
        if not isinstance(record, dict):
            continue
        record_type = str(record.get("record_type", ""))
        if not record_type.startswith("evidence.capture."):
            continue
        ts = record.get("ts_start_utc") or record.get("ts_utc")
        if not _within_window(ts, time_window):
            continue
        evidence.append((_ts_value(ts), str(record_id)))
    evidence.sort(key=lambda item: (-item[0], item[1]))
    if evidence:
        return [record_id for _ts, record_id in evidence[:max_limit]]

    # Final fallback: direct read-only sqlite query for sidecar-managed DBs where
    # metadata capability reads are intermittently blocked by file locks.
    db_path = None
    try:
        store = getattr(metadata, "_store", None)
        db_path = getattr(store, "_db_path", None)
    except Exception:
        db_path = None
    if isinstance(db_path, str) and db_path:
        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
            try:
                cur = con.execute(
                    "SELECT id, ts_utc FROM metadata WHERE record_type LIKE 'evidence.capture.%' ORDER BY ts_utc DESC, id DESC LIMIT ?",
                    (max(100, max_limit * 10),),
                )
                rows = cur.fetchall()
            finally:
                con.close()
            for rid, ts in rows:
                if not _within_window(ts, time_window):
                    continue
                evidence.append((_ts_value(ts), str(rid)))
            evidence.sort(key=lambda item: (-item[0], item[1]))
            return [record_id for _ts, record_id in evidence[:max_limit]]
        except Exception:
            return []
    return []


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
                signal = None
                try:
                    signal = load_activity_signal(system.config)
                except Exception:
                    signal = None
                if signal is not None:
                    idle_seconds = float(signal.idle_seconds)
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

    # Query-time tactical extractors are intentionally disabled.
    # Answers must come from persisted derived records produced at processing time.
    custom_claims: list[dict[str, Any]] = []
    custom_claims_error: str | None = None
    custom_claims_debug: dict[str, Any] = {"mode": "persisted_only"}

    # Optional: LLM synthesizer that emits quote-grounded claims, converted into
    # verifiable citations. This runs strictly over already-extracted text.
    synth_claims: list[dict[str, Any]] = []
    synth_debug: dict[str, Any] = {}
    synth_error: str | None = None
    query_cfg = system.config.get("query", {}) if hasattr(system, "config") else {}
    synth_enabled = bool(query_cfg.get("enable_synthesizer", False)) if isinstance(query_cfg, dict) else False
    try:
        synthesizer = None
        if hasattr(system, "get"):
            try:
                synthesizer = _resolve_single_provider(system.get("answer.synthesizer"))
            except Exception:
                synthesizer = None
        if synth_enabled and synthesizer is not None and metadata is not None and query_ledger_hash and anchor_ref:
            evidence_items: list[dict[str, Any]] = []
            for item in (results[:10] if isinstance(results, list) else []):
                rid = str(item.get("derived_id") or "").strip()
                if not rid:
                    continue
                rec = metadata.get(rid, {})
                if not isinstance(rec, dict):
                    continue
                txt = rec.get("text", "")
                if not isinstance(txt, str) or not txt.strip():
                    continue
                evidence_items.append(
                    {
                        "record_id": rid,
                        "text": txt,
                        "ts_utc": rec.get("ts_utc") or rec.get("ts_start_utc") or rec.get("ts_end_utc"),
                    }
                )
            synth_debug["evidence_items"] = int(len(evidence_items))
            if evidence_items and hasattr(synthesizer, "synthesize"):
                try:
                    synth_out = synthesizer.synthesize(query_text, evidence_items, max_claims=3)
                except TypeError:
                    # Back-compat for plugins that don't accept keyword args.
                    synth_out = synthesizer.synthesize(query_text, evidence_items)
                if isinstance(synth_out, dict):
                    synth_debug["backend"] = synth_out.get("backend")
                    synth_debug["model"] = synth_out.get("model")
                    if synth_out.get("error"):
                        synth_error = str(synth_out.get("error"))
                    raw_claims = synth_out.get("claims", [])
                else:
                    raw_claims = []

                if isinstance(raw_claims, list) and raw_claims:
                    for claim in raw_claims[:6]:
                        if not isinstance(claim, dict):
                            continue
                        claim_text = str(claim.get("text") or "").strip()
                        ev = claim.get("evidence", [])
                        if not claim_text or not isinstance(ev, list) or not ev:
                            continue
                        citations: list[dict[str, Any]] = []
                        for ev_item in ev[:6]:
                            if not isinstance(ev_item, dict):
                                continue
                            derived_id = str(ev_item.get("record_id") or "").strip()
                            quote = str(ev_item.get("quote") or "")
                            if not derived_id or not quote:
                                continue
                            derived = metadata.get(derived_id, {})
                            if not isinstance(derived, dict):
                                continue
                            evidence_id = str(derived.get("source_id") or "").strip()
                            if not evidence_id:
                                continue
                            evidence_rec = metadata.get(evidence_id, {})
                            if not isinstance(evidence_rec, dict):
                                continue
                            derived_text = str(derived.get("text") or "")
                            start = derived_text.find(quote)
                            if start < 0:
                                continue
                            end = start + len(quote)
                            derived_hash = _record_hash(derived)
                            evidence_hash = _record_hash(evidence_rec)
                            if not derived_hash or not evidence_hash:
                                continue
                            locator = _citation_locator(
                                kind="text_offsets",
                                record_id=derived_id,
                                record_hash=str(derived_hash),
                                offset_start=int(start),
                                offset_end=int(end),
                                span_text=quote,
                            )
                            citations.append(
                                {
                                    "schema_version": 1,
                                    "locator": locator,
                                    "span_id": evidence_id,
                                    "evidence_id": evidence_id,
                                    "evidence_hash": evidence_hash,
                                    "derived_id": derived_id,
                                    "derived_hash": derived_hash,
                                    "span_kind": "text",
                                    "span_ref": derived.get("span_ref") if isinstance(derived, dict) else None,
                                    "ledger_head": query_ledger_hash,
                                    "anchor_ref": anchor_ref,
                                    "source": "synth",
                                    "offset_start": int(start),
                                    "offset_end": int(end),
                                }
                            )
                        if citations:
                            synth_claims.append({"text": claim_text, "citations": citations})
    except Exception:
        try:
            import traceback

            synth_error = traceback.format_exc(limit=2).strip()
        except Exception:
            synth_error = "synth_exception"

    claims = []
    stale_hits: list[str] = []
    for claim in custom_claims:
        claims.append(claim)
    for claim in synth_claims:
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
        if evidence_hash is None:
            evidence_hash = hash_text(normalize_text(str(text or evidence_id)))
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
        if not locator_record_hash:
            locator_record_hash = hash_text(normalize_text(str(text or locator_record_id)))
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
        "synth_claims": {
            "count": int(len(synth_claims)),
            "error": synth_error,
            "debug": synth_debug,
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


def _append_query_metric(system, *, query: str, method: str, result: dict[str, Any]) -> None:
    config = getattr(system, "config", {}) if system is not None else {}
    if not isinstance(config, dict):
        return
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    evaluation = result.get("evaluation", {}) if isinstance(result.get("evaluation", {}), dict) else {}
    custom_claims = result.get("custom_claims", {}) if isinstance(result.get("custom_claims", {}), dict) else {}
    synth_claims = result.get("synth_claims", {}) if isinstance(result.get("synth_claims", {}), dict) else {}
    prov = result.get("provenance", {}) if isinstance(result.get("provenance", {}), dict) else {}
    processing = result.get("processing", {}) if isinstance(result.get("processing", {}), dict) else {}
    extraction = processing.get("extraction", {}) if isinstance(processing.get("extraction", {}), dict) else {}
    synth_debug = synth_claims.get("debug", {}) if isinstance(synth_claims.get("debug", {}), dict) else {}
    payload = {
        "schema_version": 1,
        "record_type": "derived.query.eval",
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "query": str(query or ""),
        "query_sha256": sha256_text(str(query or "")),
        "method": str(method or ""),
        "answer_state": str(answer.get("state") or ""),
        "claim_count": int(len(answer.get("claims", []))) if isinstance(answer.get("claims", []), list) else 0,
        "result_count": int(len(result.get("results", []))) if isinstance(result.get("results", []), list) else 0,
        "coverage_bp": int(round(float(evaluation.get("coverage_ratio", 0.0) or 0.0) * 10000.0)),
        "missing_spans_count": int(evaluation.get("missing_spans_count", 0) or 0),
        "blocked_extract": bool(evaluation.get("blocked_extract", False)),
        "blocked_reason": str(evaluation.get("blocked_reason") or ""),
        "custom_claims_count": int(custom_claims.get("count", 0) or 0),
        "synth_claims_count": int(synth_claims.get("count", 0) or 0),
        "synth_error": str(synth_claims.get("error") or ""),
        "synth_backend": str(synth_debug.get("backend") or ""),
        "synth_model": str(synth_debug.get("model") or ""),
        "query_ledger_head": str(prov.get("query_ledger_head") or ""),
        "anchor_ref": str(prov.get("anchor_ref") or ""),
        "extracted_count": int(extraction.get("extracted_count", 0) or 0),
        "candidate_count": int(extraction.get("candidate_count", 0) or 0),
    }
    try:
        _ = append_fact_line(config, rel_path="query_eval.ndjson", payload=payload)
    except Exception:
        pass


def _query_tokens(query: str) -> set[str]:
    tokens = [tok for tok in normalize_text(str(query or "")).split() if len(tok) >= 2]
    return {tok for tok in tokens}


def _compact_line(text: str, *, limit: int = 180) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= int(limit):
        return normalized
    return normalized[: max(0, int(limit) - 1)].rstrip() + "…"


def _extract_first_match(patterns: list[str], texts: list[str]) -> str | None:
    for text in texts:
        for pattern in patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                value = str(m.group(1) or "").strip()
                if value:
                    return value
    return None


def _extract_observation_fields(claim_texts: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    inboxes = _extract_first_match(
        [r"\bopen_inboxes_count\s*=\s*(\d+)\b", r"\bopen inboxes:\s*(\d+)\b"],
        claim_texts,
    )
    if inboxes:
        out["open_inboxes"] = inboxes
    vdi_time = _extract_first_match(
        [r"\bvdi_clock_time\s*=\s*([0-9]{1,2}:[0-9]{2}\s*[AP]M)\b", r"\bvdi time:\s*([0-9]{1,2}:[0-9]{2}\s*[AP]M)\b"],
        claim_texts,
    )
    if vdi_time:
        out["vdi_time"] = vdi_time
    song = _extract_first_match(
        [r"\bcurrent_song\s*=\s*([^\n]+)", r"\bnow playing:\s*([^\n]+)"],
        claim_texts,
    )
    if song:
        song_clean = song.strip().rstrip(".")
        if ". Now playing:" in song_clean:
            tail = song_clean.split(". Now playing:", 1)[1].strip()
            if tail:
                song_clean = f"Now playing: {tail}"
        out["song"] = song_clean
    collaborator = _extract_first_match(
        [
            r"\bquorum_message_collaborator\s*=\s*([A-Za-z][A-Za-z '\-]{1,80})(?=$|[.;])",
            r"\bquorum_task_collaborator\s*=\s*([A-Za-z][A-Za-z '\-]{1,80})(?=$|[.;])",
            r"\bquorum (?:message|task) collaborator:\s*([A-Za-z][A-Za-z '\-]{1,80})(?=$|[.;])",
        ],
        claim_texts,
    )
    if collaborator:
        out["quorum_collaborator"] = collaborator.strip().rstrip(".")
    return out


def _extract_inbox_trace_bullets(claim_texts: list[str]) -> list[str]:
    trace_text = ""
    for text in claim_texts:
        if "Inbox count trace:" in text:
            trace_text = text
            break
    if not trace_text:
        return []
    bullets: list[str] = []
    metrics = re.search(
        r"token_count=(\d+),\s*mail_context_count=(\d+),\s*line_count=(\d+),\s*final_count=(\d+)",
        trace_text,
        flags=re.IGNORECASE,
    )
    if metrics:
        bullets.append(
            "signals:"
            f" explicit_inbox_labels={metrics.group(1)},"
            f" mail_client_regions={metrics.group(2)},"
            f" mail_lines={metrics.group(3)},"
            f" total={metrics.group(4)}"
        )
    token_hits = re.findall(
        r"token:\s*([^@|]+?)\s*@\s*\[([^\]]+)\]",
        trace_text,
        flags=re.IGNORECASE,
    )
    for idx, (label, bbox) in enumerate(token_hits[:4], start=1):
        bullets.append(f"match_{idx}: {_compact_line(label, limit=48)} @ [{bbox}]")
    return bullets


def _build_answer_display(query: str, claim_texts: list[str]) -> dict[str, Any]:
    low_query = str(query or "").casefold()
    fields = _extract_observation_fields(claim_texts)
    summary = ""
    bullets: list[str] = []
    structured = False
    topic = "generic"

    if "inbox" in low_query and fields.get("open_inboxes"):
        summary = f"inboxes: {fields['open_inboxes']}"
        bullets.extend(_extract_inbox_trace_bullets(claim_texts))
        structured = True
        topic = "inbox"
    elif ("song" in low_query or "playing" in low_query) and fields.get("song"):
        summary = f"song: {fields['song']}"
        structured = True
        topic = "song"
    elif ("quorum" in low_query or "working with me" in low_query) and fields.get("quorum_collaborator"):
        summary = f"quorum_collaborator: {fields['quorum_collaborator']}"
        structured = True
        topic = "quorum"
    elif ("vdi" in low_query or "time" in low_query) and fields.get("vdi_time"):
        summary = f"vdi_time: {fields['vdi_time']}"
        structured = True
        topic = "vdi"

    if not summary:
        if fields.get("open_inboxes"):
            summary = f"inboxes: {fields['open_inboxes']}"
            structured = True
            topic = "inbox"
        elif fields.get("quorum_collaborator"):
            summary = f"quorum_collaborator: {fields['quorum_collaborator']}"
            structured = True
            topic = "quorum"
        elif fields.get("song"):
            summary = f"song: {fields['song']}"
            structured = True
            topic = "song"
        elif fields.get("vdi_time"):
            summary = f"vdi_time: {fields['vdi_time']}"
            structured = True
            topic = "vdi"

    if not summary:
        for text in claim_texts:
            compact = _compact_line(text, limit=220)
            if compact:
                summary = compact
                break

    if not bullets and structured:
        if topic == "song" and fields.get("song"):
            bullets.append(f"track: {fields['song']}")
        elif topic == "quorum" and fields.get("quorum_collaborator"):
            bullets.append(f"collaborator: {fields['quorum_collaborator']}")
        elif topic == "vdi" and fields.get("vdi_time"):
            bullets.append(f"clock_readout: {fields['vdi_time']}")

    if not bullets and not structured:
        compact_claims = [_compact_line(t, limit=140) for t in claim_texts if str(t or "").strip()]
        for text in compact_claims[:3]:
            if text and text != summary:
                bullets.append(text)

    return {
        "schema_version": 1,
        "summary": summary,
        "bullets": bullets,
        "fields": fields,
    }


def _apply_answer_display(query: str, result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return result
    answer = result.get("answer", {})
    if not isinstance(answer, dict):
        return result
    claim_texts = _claim_texts(result)
    display = _build_answer_display(query, claim_texts)
    answer_obj = dict(answer)
    answer_obj["display"] = display
    answer_obj["summary"] = str(display.get("summary") or "")
    result_obj = dict(result)
    result_obj["answer"] = answer_obj
    return result_obj


def _claim_texts(result: dict[str, Any]) -> list[str]:
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    claims = answer.get("claims", []) if isinstance(answer.get("claims", []), list) else []
    out: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        text = str(claim.get("text") or "").strip()
        if text:
            out.append(text)
    return out


def _citation_count(result: dict[str, Any]) -> int:
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    claims = answer.get("claims", []) if isinstance(answer.get("claims", []), list) else []
    total = 0
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        cites = claim.get("citations", [])
        if isinstance(cites, list):
            total += len(cites)
    return int(total)


def _is_count_query(query: str) -> bool:
    low = str(query or "").casefold()
    return any(marker in low for marker in ("how many", "count", "number of"))


def _has_numeric_claim(result: dict[str, Any]) -> bool:
    for text in _claim_texts(result):
        if re.search(r"\b\d+\b", text):
            return True
    return False


def _score_query_result(query: str, result: dict[str, Any]) -> dict[str, Any]:
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    state = str(answer.get("state") or "")
    state_score = {"ok": 40.0, "partial": 20.0, "no_evidence": 0.0, "error": -20.0}.get(state, 0.0)
    claim_texts = _claim_texts(result)
    claim_count = int(len(claim_texts))
    citation_count = _citation_count(result)
    q_tokens = _query_tokens(query)
    claim_tokens: set[str] = set()
    for text in claim_texts:
        claim_tokens |= _query_tokens(text)
    overlap = int(len(q_tokens & claim_tokens))
    overlap_ratio = (float(overlap) / float(len(q_tokens))) if q_tokens else 0.0
    overlap_score = float(round(overlap_ratio * 30.0, 3))
    claims_score = float(min(20, claim_count * 4))
    citations_score = float(min(20, citation_count * 2))
    coverage_ratio = 0.0
    evaluation = result.get("evaluation", {}) if isinstance(result.get("evaluation", {}), dict) else {}
    try:
        coverage_ratio = float(evaluation.get("coverage_ratio", 0.0) or 0.0)
    except Exception:
        coverage_ratio = 0.0
    coverage_score = float(round(min(1.0, max(0.0, coverage_ratio)) * 10.0, 3))
    numeric_bonus = 0.0
    if _is_count_query(query):
        numeric_bonus = 12.0 if _has_numeric_claim(result) else -4.0
    total = float(round(state_score + claims_score + citations_score + overlap_score + coverage_score + numeric_bonus, 3))
    return {
        "total": total,
        "state": state,
        "components": {
            "state_score": state_score,
            "claims_score": claims_score,
            "citations_score": citations_score,
            "overlap_score": overlap_score,
            "coverage_score": coverage_score,
            "numeric_bonus": numeric_bonus,
            "query_token_count": int(len(q_tokens)),
            "overlap_tokens": int(overlap),
            "claim_count": int(claim_count),
            "citation_count": int(citation_count),
            "coverage_ratio": float(round(coverage_ratio, 6)),
        },
    }


def run_query(system, query: str, *, schedule_extract: bool = False) -> dict[str, Any]:
    state_cfg = system.config.get("processing", {}).get("state_layer", {}) if hasattr(system, "config") else {}
    if isinstance(state_cfg, dict) and bool(state_cfg.get("query_enabled", False)):
        state_result = run_state_query(system, query)
        classic_result = run_query_without_state(system, query, schedule_extract=bool(schedule_extract))
        state_score = _score_query_result(query, state_result)
        classic_score = _score_query_result(query, classic_result)

        prefer_classic = bool(classic_score.get("total", 0.0) >= state_score.get("total", 0.0))
        if prefer_classic:
            merged = _merge_state_fallback(state_result, classic_result)
            processing = merged.get("processing", {}) if isinstance(merged.get("processing", {}), dict) else {}
            processing["arbitration"] = {
                "winner": "classic",
                "state_score": state_score,
                "classic_score": classic_score,
            }
            merged["processing"] = processing
            merged = _apply_answer_display(query, merged)
            _append_query_metric(system, query=query, method="classic_arbitrated", result=merged)
            return merged

        result = dict(state_result)
        processing = result.get("processing", {}) if isinstance(result.get("processing", {}), dict) else {}
        processing["arbitration"] = {
            "winner": "state",
            "state_score": state_score,
            "classic_score": classic_score,
        }
        result["processing"] = processing
        result = _apply_answer_display(query, result)
        _append_query_metric(system, query=query, method="state_arbitrated", result=result)
        return result
    result = run_query_without_state(system, query, schedule_extract=bool(schedule_extract))
    result = _apply_answer_display(query, result)
    _append_query_metric(system, query=query, method="classic", result=result)
    return result
