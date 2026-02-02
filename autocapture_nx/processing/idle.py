"""Idle-time processing for OCR/VLM extraction."""

from __future__ import annotations

import io
import zipfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from autocapture_nx.kernel.derived_records import (
    build_derivation_edge,
    build_text_record,
    derivation_edge_id,
    extract_text_payload,
)
from autocapture_nx.kernel.frame_evidence import ensure_frame_evidence
from autocapture.indexing.factory import build_indexes
from autocapture_nx.kernel.ids import encode_record_id_component


@dataclass
class IdleProcessStats:
    scanned: int = 0
    processed: int = 0
    ocr_ok: int = 0
    vlm_ok: int = 0
    sst_runs: int = 0
    sst_heavy: int = 0
    sst_tokens: int = 0
    skipped: int = 0
    errors: int = 0
    state_runs: int = 0
    state_spans: int = 0
    state_edges: int = 0
    state_evidence: int = 0
    state_errors: int = 0


@dataclass
class IdleCheckpoint:
    last_record_id: str | None
    processed_total: int
    updated_utc: str


def _derive_run_id(config: dict[str, Any], record_id: str) -> str:
    if "/" in record_id:
        return record_id.split("/", 1)[0]
    return str(config.get("runtime", {}).get("run_id", "run"))


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


def _get_media_blob(store: Any, record_id: str) -> bytes | None:
    if hasattr(store, "get"):
        return store.get(record_id)
    if hasattr(store, "get_stream"):
        handle = store.get_stream(record_id)
        if hasattr(handle, "read"):
            data = handle.read()
            if hasattr(handle, "close"):
                try:
                    handle.close()
                except Exception:
                    pass
            return data
    return None


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


class IdleProcessor:
    def __init__(self, system: Any) -> None:
        self._system = system
        self._config = getattr(system, "config", {}) if system is not None else {}
        self._metadata = self._cap("storage.metadata")
        self._media = self._cap("storage.media")
        self._ocr = self._cap("ocr.engine")
        self._vlm = self._cap("vision.extractor")
        self._pipeline = self._cap("processing.pipeline")
        self._events = self._cap("event.builder")
        self._logger = self._cap("observability.logger")
        self._lexical = None
        self._vector = None
        self._indexes_ready = False
        self._checkpoint_loaded = False
        self._checkpoint: IdleCheckpoint | None = None
        self._state_processor = None

    def _cap(self, name: str) -> Any | None:
        if hasattr(self._system, "has") and self._system.has(name):
            return self._system.get(name)
        if isinstance(self._system, dict):
            return self._system.get(name)
        return None

    def _checkpoint_id(self) -> str:
        run_id = str(self._config.get("runtime", {}).get("run_id", "run"))
        return f"{run_id}/derived.idle.checkpoint"

    def _load_checkpoint(self) -> IdleCheckpoint | None:
        if self._checkpoint_loaded:
            return self._checkpoint
        self._checkpoint_loaded = True
        if self._metadata is None:
            return None
        record = self._metadata.get(self._checkpoint_id(), None)
        if isinstance(record, dict) and record.get("record_type") == "derived.idle.checkpoint":
            last_record_id = record.get("last_record_id")
            processed_total = int(record.get("processed_total", 0) or 0)
            updated = str(record.get("ts_utc") or "")
            if updated:
                self._checkpoint = IdleCheckpoint(last_record_id=str(last_record_id) if last_record_id else None, processed_total=processed_total, updated_utc=updated)
        return self._checkpoint

    def _store_checkpoint(self, last_record_id: str, processed_total: int) -> None:
        if self._metadata is None:
            return
        ts_utc = datetime.now(timezone.utc).isoformat()
        run_id = str(self._config.get("runtime", {}).get("run_id", "run"))
        payload = {
            "record_type": "derived.idle.checkpoint",
            "run_id": run_id,
            "ts_utc": ts_utc,
            "last_record_id": last_record_id,
            "processed_total": int(processed_total),
        }
        if hasattr(self._metadata, "put_replace"):
            try:
                self._metadata.put_replace(self._checkpoint_id(), payload)
            except Exception:
                self._metadata.put(self._checkpoint_id(), payload)
        else:
            self._metadata.put(self._checkpoint_id(), payload)
        self._checkpoint = IdleCheckpoint(last_record_id=last_record_id, processed_total=int(processed_total), updated_utc=ts_utc)
        if self._events is not None:
            try:
                event_id = self._events.journal_event("idle.checkpoint", payload, event_id=self._checkpoint_id(), ts_utc=ts_utc)
                self._events.ledger_entry(
                    "idle.checkpoint",
                    inputs=[],
                    outputs=[event_id],
                    payload=payload,
                    entry_id=event_id,
                    ts_utc=ts_utc,
                )
            except Exception:
                pass

    def _record_ids(self) -> list[str]:
        if self._metadata is None:
            return []
        keys = list(getattr(self._metadata, "keys", lambda: [])())
        keys.sort()
        return keys

    def _ensure_indexes(self) -> None:
        if self._indexes_ready:
            return
        self._indexes_ready = True
        if not isinstance(self._config, dict) or not self._config:
            return
        try:
            self._lexical, self._vector = build_indexes(self._config)
        except Exception as exc:
            self._lexical = None
            self._vector = None
            if self._logger is not None:
                self._logger.log("index.init_failed", {"error": str(exc)})

    def _resolve_state_processor(self):
        if self._state_processor is not None:
            return self._state_processor
        try:
            from autocapture_nx.state_layer.processor import StateTapeProcessor
        except Exception:
            return None
        self._state_processor = StateTapeProcessor(self._system)
        return self._state_processor

    def _index_text(self, doc_id: str, text: str) -> None:
        if not text:
            return
        if self._lexical is not None:
            try:
                self._lexical.index(doc_id, text)
            except Exception as exc:
                if self._logger is not None:
                    self._logger.log("index.lexical_error", {"doc_id": doc_id, "error": str(exc)})
        if self._vector is not None:
            try:
                self._vector.index(doc_id, text)
            except Exception as exc:
                if self._logger is not None:
                    self._logger.log("index.vector_error", {"doc_id": doc_id, "error": str(exc)})

    def process(self, *, should_abort: Callable[[], bool] | None = None) -> IdleProcessStats:
        done, stats = self.process_step(should_abort=should_abort, budget_ms=0, persist_checkpoint=False)
        _ = done
        return stats

    def process_step(
        self,
        *,
        should_abort: Callable[[], bool] | None = None,
        budget_ms: int = 0,
        persist_checkpoint: bool = True,
    ) -> tuple[bool, IdleProcessStats]:
        stats = IdleProcessStats()
        if self._metadata is None or self._media is None:
            return True, stats
        self._ensure_indexes()
        idle_cfg = self._config.get("processing", {}).get("idle", {})
        max_items = int(idle_cfg.get("max_items_per_run", 20))
        max_seconds = int(idle_cfg.get("max_seconds_per_run", 30))
        extractors = idle_cfg.get("extractors", {})
        allow_ocr = bool(extractors.get("ocr", True))
        allow_vlm = bool(extractors.get("vlm", True))
        sst_cfg = self._config.get("processing", {}).get("sst", {})
        pipeline_enabled = bool(sst_cfg.get("enabled", True)) and self._pipeline is not None
        start_mono = time.monotonic()
        start_wall = time.time()
        deadline_mono = start_mono + max(1, max_seconds)
        deadline_wall = start_wall + max(1, max_seconds)
        budget_mono = None
        budget_wall = None
        if budget_ms and budget_ms > 0:
            budget_mono = start_mono + (budget_ms / 1000.0)
            budget_wall = start_wall + (budget_ms / 1000.0)

        def _expired() -> bool:
            now = time.monotonic()
            if now >= deadline_mono:
                return True
            if budget_mono is not None and now >= budget_mono:
                return True
            return False

        record_ids = self._record_ids()
        evidence_ids = []
        for record_id in record_ids:
            record = self._metadata.get(record_id, {})
            record_type = str(record.get("record_type", ""))
            if record_type.startswith("evidence.capture."):
                evidence_ids.append(record_id)

        start_index = 0
        checkpoint = self._load_checkpoint() if persist_checkpoint else None
        if checkpoint and checkpoint.last_record_id in evidence_ids:
            start_index = evidence_ids.index(checkpoint.last_record_id) + 1

        processed_total = checkpoint.processed_total if checkpoint else 0
        last_record_id: str | None = None
        aborted = False

        for record_id in evidence_ids[start_index:]:
            source_record_id = record_id
            if should_abort and should_abort():
                aborted = True
                break
            if _expired():
                break
            record = self._metadata.get(record_id, {})
            record_type = str(record.get("record_type", ""))
            if not record_type.startswith("evidence.capture."):
                stats.skipped += 1
                last_record_id = source_record_id
                continue
            stats.scanned += 1

            blob = _get_media_blob(self._media, record_id)
            if not blob:
                stats.errors += 1
                last_record_id = source_record_id
                continue
            frame = _extract_frame(blob, record)
            if not frame:
                stats.errors += 1
                last_record_id = source_record_id
                continue

            record_id, record = ensure_frame_evidence(
                config=self._config,
                metadata=self._metadata,
                media=self._media,
                record_id=record_id,
                record=record if isinstance(record, dict) else {},
                frame_bytes=frame,
                event_builder=self._events,
                logger=self._logger,
            )
            run_id = _derive_run_id(self._config, record_id)
            ts_utc = record.get("ts_utc") or record.get("ts_start_utc")
            ts_utc = ts_utc or datetime.now(timezone.utc).isoformat()

            derived_items: list[tuple[str, str, str, Any]] = []
            encoded_source = encode_record_id_component(record_id)
            if allow_ocr and self._ocr is not None:
                for provider_id, extractor in _capability_providers(self._ocr, "ocr.engine"):
                    provider_component = encode_record_id_component(provider_id)
                    derived_items.append(
                        (
                            "ocr",
                            provider_id,
                            f"{run_id}/derived.text.ocr/{provider_component}/{encoded_source}",
                            extractor,
                        )
                    )
            if allow_vlm and self._vlm is not None:
                for provider_id, extractor in _capability_providers(self._vlm, "vision.extractor"):
                    provider_component = encode_record_id_component(provider_id)
                    derived_items.append(
                        (
                            "vlm",
                            provider_id,
                            f"{run_id}/derived.text.vlm/{provider_component}/{encoded_source}",
                            extractor,
                        )
                    )
            if not derived_items:
                stats.skipped += 1
                last_record_id = source_record_id
                continue

            pipeline = self._pipeline
            if pipeline_enabled and pipeline is not None and hasattr(pipeline, "process_record"):
                try:
                    result = pipeline.process_record(
                        record_id=record_id,
                        record=record,
                        frame_bytes=frame,
                        allow_ocr=allow_ocr,
                        allow_vlm=allow_vlm,
                        should_abort=should_abort,
                        deadline_ts=budget_wall if budget_wall is not None else deadline_wall,
                    )
                except Exception as exc:
                    stats.errors += 1
                    if self._logger is not None:
                        self._logger.log("sst.pipeline_error", {"source_id": record_id, "error": str(exc)})
                    last_record_id = source_record_id
                    continue
                stats.sst_runs += 1
                stats.sst_heavy += int(result.heavy_ran)
                stats.sst_tokens += int(result.ocr_tokens)
                stats.processed += int(result.derived_records)
                processed_total += int(result.derived_records)
                last_record_id = source_record_id
                if stats.processed >= max_items:
                    break
                continue

            for kind, provider_id, derived_id, extractor in derived_items:
                if should_abort and should_abort():
                    aborted = True
                    break
                if _expired():
                    break
                if self._metadata.get(derived_id):
                    continue
                try:
                    text = extract_text_payload(extractor.extract(frame))
                except Exception as exc:
                    stats.errors += 1
                    if self._logger is not None:
                        self._logger.log("derived.extract_error", {"source_id": record_id, "error": str(exc)})
                    continue
                payload = build_text_record(
                    kind=kind,
                    text=text,
                    source_id=record_id,
                    source_record=record,
                    provider_id=provider_id,
                    config=self._config,
                    ts_utc=ts_utc,
                )
                if not payload:
                    continue
                if hasattr(self._metadata, "put_new"):
                    try:
                        self._metadata.put_new(derived_id, payload)
                    except Exception:
                        continue
                else:
                    self._metadata.put(derived_id, payload)
                self._index_text(derived_id, payload.get("text", ""))
                stats.processed += 1
                processed_total += 1
                if kind == "ocr":
                    stats.ocr_ok += 1
                if kind == "vlm":
                    stats.vlm_ok += 1
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
                    if hasattr(self._metadata, "put_new"):
                        try:
                            self._metadata.put_new(edge_id, edge_payload)
                        except Exception:
                            edge_id = None
                    else:
                        self._metadata.put(edge_id, edge_payload)
                except Exception:
                    edge_id = None
                if self._events is not None:
                    event_payload = dict(payload)
                    event_payload["derived_id"] = derived_id
                    if edge_id:
                        event_payload["derivation_edge_id"] = edge_id
                    parent_hash = record.get("content_hash")
                    if parent_hash:
                        event_payload["parent_content_hash"] = parent_hash
                    self._events.journal_event("derived.extract", event_payload, event_id=derived_id, ts_utc=ts_utc)
                    self._events.ledger_entry(
                        "derived.extract",
                        inputs=[record_id],
                        outputs=[derived_id] + ([edge_id] if edge_id else []),
                        payload=event_payload,
                        entry_id=derived_id,
                        ts_utc=ts_utc,
                    )
                if stats.processed >= max_items:
                    break
            last_record_id = source_record_id
            if aborted or _expired() or stats.processed >= max_items:
                break

        state_done = True
        state_cfg = self._config.get("processing", {}).get("state_layer", {}) if isinstance(self._config, dict) else {}
        if not aborted and not _expired() and isinstance(state_cfg, dict) and bool(state_cfg.get("enabled", False)):
            processor = self._resolve_state_processor()
            if processor is not None:
                def _state_abort() -> bool:
                    if should_abort and should_abort():
                        return True
                    return _expired()

                try:
                    state_done, state_stats = processor.process_step(
                        should_abort=_state_abort,
                        budget_ms=budget_ms,
                    )
                    stats.state_runs += 1
                    stats.state_spans += int(getattr(state_stats, "spans_inserted", 0))
                    stats.state_edges += int(getattr(state_stats, "edges_inserted", 0))
                    stats.state_evidence += int(getattr(state_stats, "evidence_inserted", 0))
                    stats.state_errors += int(getattr(state_stats, "errors", 0))
                except Exception as exc:
                    stats.state_errors += 1
                    state_done = False
                    if self._logger is not None:
                        self._logger.log("state_tape.process_error", {"error": str(exc)})

        if persist_checkpoint and last_record_id:
            self._store_checkpoint(last_record_id, processed_total)

        done = (
            not aborted
            and (start_index >= len(evidence_ids) or (last_record_id == evidence_ids[-1] if evidence_ids else True))
            and not _expired()
            and bool(state_done)
        )
        return done, stats
