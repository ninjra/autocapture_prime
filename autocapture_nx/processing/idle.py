"""Idle-time processing for OCR/VLM extraction."""

from __future__ import annotations

import io
import zipfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

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

    def _cap(self, name: str) -> Any | None:
        if hasattr(self._system, "has") and self._system.has(name):
            return self._system.get(name)
        if isinstance(self._system, dict):
            return self._system.get(name)
        return None

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
        stats = IdleProcessStats()
        if self._metadata is None or self._media is None:
            return stats
        self._ensure_indexes()
        idle_cfg = self._config.get("processing", {}).get("idle", {})
        max_items = int(idle_cfg.get("max_items_per_run", 20))
        max_seconds = int(idle_cfg.get("max_seconds_per_run", 30))
        extractors = idle_cfg.get("extractors", {})
        allow_ocr = bool(extractors.get("ocr", True))
        allow_vlm = bool(extractors.get("vlm", True))
        sst_cfg = self._config.get("processing", {}).get("sst", {})
        pipeline_enabled = bool(sst_cfg.get("enabled", True)) and self._pipeline is not None
        deadline = time.time() + max(1, max_seconds)

        keys = list(getattr(self._metadata, "keys", lambda: [])())
        for record_id in keys:
            if should_abort and should_abort():
                break
            if time.time() >= deadline:
                break
            record = self._metadata.get(record_id, {})
            record_type = str(record.get("record_type", ""))
            if not record_type.startswith("evidence.capture."):
                stats.skipped += 1
                continue
            stats.scanned += 1
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
                continue

            blob = _get_media_blob(self._media, record_id)
            if not blob:
                stats.errors += 1
                continue
            frame = _extract_frame(blob, record)
            if not frame:
                stats.errors += 1
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
                        deadline_ts=deadline,
                    )
                except Exception as exc:
                    stats.errors += 1
                    if self._logger is not None:
                        self._logger.log("sst.pipeline_error", {"source_id": record_id, "error": str(exc)})
                    continue
                stats.sst_runs += 1
                stats.sst_heavy += int(result.heavy_ran)
                stats.sst_tokens += int(result.ocr_tokens)
                stats.processed += int(result.derived_records)
                if stats.processed >= max_items:
                    break
                continue

            for kind, provider_id, derived_id, extractor in derived_items:
                if should_abort and should_abort():
                    break
                if time.time() >= deadline:
                    break
                if self._metadata.get(derived_id):
                    continue
                try:
                    text = extractor.extract(frame).get("text", "")
                except Exception as exc:
                    stats.errors += 1
                    if self._logger is not None:
                        self._logger.log("derived.extract_error", {"source_id": record_id, "error": str(exc)})
                    continue
                if not text:
                    continue
                payload = {
                    "record_type": f"derived.text.{kind}",
                    "ts_utc": ts_utc,
                    "text": text,
                    "source_id": record_id,
                    "method": kind,
                    "provider_id": provider_id,
                }
                model_name = self._config.get("models", {}).get("vlm_path") if kind == "vlm" else None
                if model_name:
                    payload["model_id"] = model_name
                if hasattr(self._metadata, "put_new"):
                    try:
                        self._metadata.put_new(derived_id, payload)
                    except Exception:
                        continue
                else:
                    self._metadata.put(derived_id, payload)
                self._index_text(derived_id, text)
                stats.processed += 1
                if kind == "ocr":
                    stats.ocr_ok += 1
                if kind == "vlm":
                    stats.vlm_ok += 1
                if self._events is not None:
                    event_payload = dict(payload)
                    event_payload["derived_id"] = derived_id
                    self._events.journal_event("derived.extract", event_payload, event_id=derived_id, ts_utc=ts_utc)
                    self._events.ledger_entry(
                        "derived.extract",
                        inputs=[record_id],
                        outputs=[derived_id],
                        payload=event_payload,
                        entry_id=derived_id,
                        ts_utc=ts_utc,
                    )
            if stats.processed >= max_items:
                break
        return stats
