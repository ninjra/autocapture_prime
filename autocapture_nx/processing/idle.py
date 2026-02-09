"""Idle-time processing for OCR/VLM extraction."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import zipfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from autocapture_nx.kernel.derived_records import (
    build_derivation_edge,
    build_text_record,
    derived_text_record_id,
    derivation_edge_id,
)
from autocapture_nx.kernel.frame_evidence import ensure_frame_evidence
from autocapture.indexing.factory import build_indexes
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.kernel.providers import capability_providers
from autocapture_nx.processing.qa.fixture_answers import extract_fixture_answers


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


@dataclass(frozen=True)
class _IdleWorkItem:
    source_id: str
    record_id: str
    record: dict[str, Any]
    frame_bytes: bytes
    run_id: str
    ts_utc: str
    encoded_source: str
    parent_hash: str | None
    missing_count: int
    needs_pipeline: bool


def _is_missing_metadata_record(value: Any) -> bool:
    """Normalize missing-record semantics across storage backends.

    Some metadata providers return `{}` for missing keys instead of `None`.
    Downstream processors must treat both as "missing" to avoid skipping work.
    """

    if value is None:
        return True
    if value == {}:
        return True
    if isinstance(value, dict):
        # Real records always carry a record_type.
        return "record_type" not in value
    # Unexpected shapes are treated as missing to force regeneration.
    return True


def _derive_run_id(config: dict[str, Any], record_id: str) -> str:
    if "/" in record_id:
        return record_id.split("/", 1)[0]
    return str(config.get("runtime", {}).get("run_id", "run"))


def _ffmpeg_path(config: dict[str, Any]) -> str | None:
    capture_cfg = config.get("capture", {}) if isinstance(config, dict) else {}
    video_cfg = capture_cfg.get("video", {}) if isinstance(capture_cfg, dict) else {}
    candidates = [
        str(video_cfg.get("ffmpeg_path", "") or "").strip(),
        str(capture_cfg.get("ffmpeg_path", "") or "").strip(),
        str(os.getenv("FFMPEG_PATH", "") or "").strip(),
    ]
    for raw in candidates:
        if not raw:
            continue
        try:
            if Path(raw).exists():
                return raw
        except Exception:
            continue
    return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


def _decode_first_frame_ffmpeg(blob: bytes, *, ffmpeg_path: str) -> bytes | None:
    if not blob:
        return None
    # MP4/MKV containers are not reliably streamable from stdin (ffmpeg may treat
    # the input as a "partial file" because it cannot seek to find moov/indices).
    # Write to a temp file for deterministic, low-friction decoding.
    import tempfile

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="autocapture_ffmpeg_", suffix=".bin", delete=False) as handle:
            tmp_path = handle.name
            handle.write(blob)
            handle.flush()
        args = [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-threads",
            "1",
            "-i",
            tmp_path,
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "pipe:1",
        ]
    except Exception:
        try:
            if tmp_path:
                os.unlink(tmp_path)
        except Exception:
            pass
        return None
    env = os.environ.copy()
    # Keep decoding lightweight in WSL and avoid thread fanout.
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("MKL_NUM_THREADS", "1")
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    env.setdefault("NUMEXPR_NUM_THREADS", "1")
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            # Large frames (e.g., high-res screen recordings) can take longer to
            # decode even when extracting a single frame. Keep this bounded but
            # not so tight that ffmpeg_mp4 fixtures always time out on WSL.
            timeout=20.0,
            check=False,
        )
    except Exception:
        try:
            if tmp_path:
                os.unlink(tmp_path)
        except Exception:
            pass
        return None
    try:
        if tmp_path:
            os.unlink(tmp_path)
    except Exception:
        pass
    if proc.returncode != 0:
        return None
    out = proc.stdout or b""
    if out.startswith(b"\x89PNG\r\n\x1a\n"):
        return out
    return None


def _extract_frame(blob: bytes, record: dict[str, Any], *, config: dict[str, Any] | None = None) -> bytes | None:
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
    if container_type in {"ffmpeg_mp4", "ffmpeg_lossless"}:
        ffmpeg = _ffmpeg_path(config or {})
        if not ffmpeg:
            return None
        return _decode_first_frame_ffmpeg(blob, ffmpeg_path=ffmpeg)
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
    return capability_providers(capability, default_provider)


def _ts_key(ts: str | None) -> float:
    if not ts:
        return 0.0
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return 0.0


def _dedupe_texts(texts: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for text in texts:
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _response_texts(response: Any) -> list[str]:
    if response is None:
        return []
    texts: list[str] = []
    if isinstance(response, dict):
        for key in ("text_plain", "caption", "text"):
            value = response.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                text = value.strip()
            else:
                text = str(value).strip()
            if text:
                texts.append(text)
        return _dedupe_texts(texts)
    if isinstance(response, str):
        text = response.strip()
        return [text] if text else []
    text = str(response).strip()
    return [text] if text else []


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

    def _ordered_evidence_ids(self, order_by: str) -> list[str]:
        if self._metadata is None:
            return []
        evidence: list[tuple[str, str | None]] = []
        for record_id in self._record_ids():
            record = self._metadata.get(record_id, {})
            record_type = str(record.get("record_type", ""))
            if not record_type.startswith("evidence.capture."):
                continue
            ts = record.get("ts_start_utc") or record.get("ts_utc")
            evidence.append((record_id, ts))
        if order_by == "ts_utc":
            evidence.sort(key=lambda item: (_ts_key(item[1]), item[0]))
        else:
            evidence.sort(key=lambda item: item[0])
        return [record_id for record_id, _ts in evidence]

    def _needs_processing(
        self,
        record_id: str,
        record: dict[str, Any],
        allow_ocr: bool,
        allow_vlm: bool,
        pipeline_enabled: bool,
    ) -> bool:
        if self._metadata is None:
            return False
        run_id = _derive_run_id(self._config, record_id)
        encoded_source = encode_record_id_component(record_id)
        derived_ids: list[str] = []
        if allow_ocr and self._ocr is not None:
            for provider_id, _extractor in _capability_providers(self._ocr, "ocr.engine"):
                derived_ids.append(
                    derived_text_record_id(
                        kind="ocr",
                        run_id=run_id,
                        provider_id=str(provider_id),
                        source_id=record_id,
                        config=self._config,
                    )
                )
        if allow_vlm and self._vlm is not None:
            for provider_id, _extractor in _capability_providers(self._vlm, "vision.extractor"):
                derived_ids.append(
                    derived_text_record_id(
                        kind="vlm",
                        run_id=run_id,
                        provider_id=str(provider_id),
                        source_id=record_id,
                        config=self._config,
                    )
                )
        if pipeline_enabled and self._pipeline is not None:
            derived_ids.append(f"{run_id}/derived.sst.frame/{encoded_source}")
        if not derived_ids:
            return False
        for derived_id in derived_ids:
            if self._metadata.get(derived_id) is None:
                return True
        return False

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
                if hasattr(self._lexical, "index_if_changed"):
                    self._lexical.index_if_changed(doc_id, text)  # type: ignore[attr-defined]
                else:
                    self._lexical.index(doc_id, text)
            except Exception as exc:
                if self._logger is not None:
                    self._logger.log("index.lexical_error", {"doc_id": doc_id, "error": str(exc)})
        if self._vector is not None:
            try:
                if hasattr(self._vector, "index_if_changed"):
                    self._vector.index_if_changed(doc_id, text)  # type: ignore[attr-defined]
                else:
                    self._vector.index(doc_id, text)
            except Exception as exc:
                if self._logger is not None:
                    self._logger.log("index.vector_error", {"doc_id": doc_id, "error": str(exc)})

    def _store_fixture_answer_doc(
        self,
        *,
        item: _IdleWorkItem,
        base_text: str,
        provider_id: str,
    ) -> None:
        """Emit deterministic QA "answer doc" lines from extracted text.

        This improves query reliability for common operator questions without
        requiring query-time media reprocessing.
        """
        if self._metadata is None:
            return
        answers = extract_fixture_answers(base_text)
        lines = answers.as_lines()
        if not lines:
            return
        doc_text = "\n".join(lines).strip()
        if not doc_text:
            return
        record_id = f"{item.run_id}/derived.text.qa/{encode_record_id_component(provider_id)}/{item.encoded_source}"
        if self._metadata.get(record_id) is not None:
            return
        payload = build_text_record(
            kind="qa",
            text=doc_text,
            source_id=item.record_id,
            source_record=item.record,
            provider_id=str(provider_id),
            config=self._config,
            ts_utc=item.ts_utc,
        )
        if not payload:
            return
        try:
            if hasattr(self._metadata, "put_new"):
                self._metadata.put_new(record_id, payload)
            else:
                self._metadata.put(record_id, payload)
        except Exception:
            return
        self._index_text(record_id, doc_text)

    def _run_provider_batch(
        self,
        extractor: Any,
        frames: list[bytes],
        *,
        max_workers: int,
    ) -> list[Any]:
        if not frames:
            return []
        batch_fn = None
        for name in ("extract_batch", "batch_extract"):
            attr = getattr(extractor, name, None)
            if callable(attr):
                batch_fn = attr
                break
        if batch_fn is not None:
            try:
                batch_outputs = batch_fn(frames)
            except Exception:
                batch_outputs = None
            if isinstance(batch_outputs, list) and len(batch_outputs) == len(frames):
                return batch_outputs
        if max_workers <= 1 or len(frames) <= 1:
            outputs: list[Any] = []
            for frame in frames:
                try:
                    outputs.append(extractor.extract(frame))
                except Exception:
                    outputs.append(None)
            return outputs
        outputs = [None for _ in frames]
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(extractor.extract, frame): idx for idx, frame in enumerate(frames)}
            for fut, idx in futures.items():
                try:
                    outputs[idx] = fut.result()
                except Exception:
                    outputs[idx] = None
        return outputs

    def _store_derived_text(
        self,
        *,
        derived_id: str,
        payload: dict[str, Any],
        record_id: str,
        record: dict[str, Any],
        kind: str,
        stats: IdleProcessStats,
    ) -> bool:
        if self._metadata is None:
            return False
        inserted = False
        if hasattr(self._metadata, "put_new"):
            try:
                self._metadata.put_new(derived_id, payload)
                inserted = True
            except Exception:
                inserted = False
        else:
            self._metadata.put(derived_id, payload)
            inserted = True
        if not inserted:
            return False
        self._index_text(derived_id, payload.get("text", ""))
        stats.processed += 1
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
            try:
                self._events.journal_event("derived.extract", event_payload, event_id=derived_id, ts_utc=payload.get("ts_utc"))
                self._events.ledger_entry(
                    "derived.extract",
                    inputs=[record_id],
                    outputs=[derived_id] + ([edge_id] if edge_id else []),
                    payload=event_payload,
                    entry_id=derived_id,
                    ts_utc=payload.get("ts_utc"),
                )
            except Exception:
                pass
        return inserted

    def _collect_work_items(
        self,
        *,
        pending_ids: list[str],
        allow_ocr: bool,
        allow_vlm: bool,
        ocr_providers: list[tuple[str, Any]],
        vlm_providers: list[tuple[str, Any]],
        max_items: int,
        should_abort: Callable[[], bool] | None,
        expired: Callable[[], bool],
        pipeline_enabled: bool,
        stats: IdleProcessStats,
    ) -> tuple[list[_IdleWorkItem], str | None, bool, int]:
        metadata = self._metadata
        if metadata is None:
            return [], None, False, 0
        items: list[_IdleWorkItem] = []
        last_record_id: str | None = None
        aborted = False
        planned = 0
        for record_id in pending_ids:
            source_record_id = record_id
            if should_abort and should_abort():
                aborted = True
                break
            if expired():
                break
            record_raw = metadata.get(record_id, {})
            record = record_raw if isinstance(record_raw, dict) else {}
            record_type = str(record.get("record_type", ""))
            if not record_type.startswith("evidence.capture."):
                stats.skipped += 1
                last_record_id = source_record_id
                continue
            if isinstance(record, dict):
                privacy_excluded = bool(
                    record.get("privacy_excluded")
                    or (isinstance(record.get("privacy"), dict) and record.get("privacy", {}).get("excluded"))
                )
                if privacy_excluded:
                    stats.skipped += 1
                    last_record_id = source_record_id
                    continue
            stats.scanned += 1
            if max_items > 0 and planned >= max_items:
                break
            blob = _get_media_blob(self._media, record_id)
            if not blob:
                stats.errors += 1
                last_record_id = source_record_id
                continue
            frame = _extract_frame(blob, record, config=self._config)
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
            missing_count = 0
            if allow_ocr:
                for provider_id, _extractor in ocr_providers:
                    derived_id = derived_text_record_id(
                        kind="ocr",
                        run_id=_derive_run_id(self._config, record_id),
                        provider_id=str(provider_id),
                        source_id=record_id,
                        config=self._config,
                    )
                    if _is_missing_metadata_record(metadata.get(derived_id)):
                        missing_count += 1
            if allow_vlm:
                for provider_id, _extractor in vlm_providers:
                    derived_id = derived_text_record_id(
                        kind="vlm",
                        run_id=_derive_run_id(self._config, record_id),
                        provider_id=str(provider_id),
                        source_id=record_id,
                        config=self._config,
                    )
                    if _is_missing_metadata_record(metadata.get(derived_id)):
                        missing_count += 1
            needs_pipeline = False
            if pipeline_enabled:
                run_id = _derive_run_id(self._config, record_id)
                frame_component = encode_record_id_component(record_id)
                frame_id = f"{run_id}/derived.sst.frame/{frame_component}"
                if _is_missing_metadata_record(metadata.get(frame_id)):
                    needs_pipeline = True
            if missing_count == 0 and not needs_pipeline:
                last_record_id = source_record_id
                continue
            run_id = _derive_run_id(self._config, record_id)
            ts_utc = record.get("ts_utc") or record.get("ts_start_utc") or datetime.now(timezone.utc).isoformat()
            encoded_source = encode_record_id_component(record_id)
            parent_hash = record.get("content_hash")
            planned += max(1, missing_count) if max_items > 0 else 0
            items.append(
                _IdleWorkItem(
                    source_id=source_record_id,
                    record_id=record_id,
                    record=record if isinstance(record, dict) else {},
                    frame_bytes=frame,
                    run_id=run_id,
                    ts_utc=ts_utc,
                    encoded_source=encoded_source,
                    parent_hash=parent_hash,
                    missing_count=missing_count,
                    needs_pipeline=needs_pipeline,
                )
            )
            last_record_id = source_record_id
            if max_items > 0 and planned >= max_items:
                break
        return items, last_record_id, aborted, planned

    def _batch_extract(
        self,
        *,
        items: list[_IdleWorkItem],
        kind: str,
        providers: list[tuple[str, Any]],
        allow: bool,
        max_workers: int,
        batch_size: int,
        should_abort: Callable[[], bool] | None,
        expired: Callable[[], bool],
        stats: IdleProcessStats,
        max_items: int,
    ) -> int:
        if not items or not allow or self._metadata is None:
            return 0
        processed = 0
        for provider_id, extractor in providers:
            if should_abort and should_abort():
                break
            if expired():
                break
            tasks: list[tuple[_IdleWorkItem, str]] = []
            provider_component = encode_record_id_component(provider_id)
            for item in items:
                derived_id = f"{item.run_id}/derived.text.{kind}/{provider_component}/{item.encoded_source}"
                if _is_missing_metadata_record(self._metadata.get(derived_id)):
                    tasks.append((item, derived_id))
            if not tasks:
                continue
            size = max(1, int(batch_size or 1))
            for start in range(0, len(tasks), size):
                if should_abort and should_abort():
                    return processed
                if expired():
                    return processed
                batch = tasks[start : start + size]
                frames = [item.frame_bytes for item, _derived_id in batch]
                outputs = self._run_provider_batch(extractor, frames, max_workers=max_workers)
                if len(outputs) != len(batch):
                    outputs = list(outputs) + [None] * max(0, len(batch) - len(outputs))
                for (item, derived_id), response in zip(batch, outputs):
                    if should_abort and should_abort():
                        return processed
                    if expired():
                        return processed
                    if max_items > 0 and stats.processed >= max_items:
                        return processed
                    if response is None:
                        stats.errors += 1
                        continue
                    texts = _response_texts(response)
                    if not texts:
                        continue
                    text = "\n\n".join(texts)
                    payload = build_text_record(
                        kind=kind,
                        text=text,
                        source_id=item.record_id,
                        source_record=item.record,
                        provider_id=provider_id,
                        config=self._config,
                        ts_utc=item.ts_utc,
                    )
                    if not payload:
                        continue
                    stored = self._store_derived_text(
                        derived_id=derived_id,
                        payload=payload,
                        record_id=item.record_id,
                        record=item.record,
                        kind=kind,
                        stats=stats,
                    )
                    if stored:
                        processed += 1
                        # After storing OCR text for an item, also emit deterministic
                        # fixture answer docs derived from that extracted text.
                        if kind == "ocr":
                            try:
                                base_text = str(payload.get("text") or "")
                                if base_text:
                                    self._store_fixture_answer_doc(item=item, base_text=base_text, provider_id="qa.fixture")
                            except Exception:
                                pass
        return processed

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
        # `processing.idle.extractors.*` controls the lightweight "derived.text.*"
        # extractors. The SST pipeline is heavier and has separate gating so we can
        # disable duplicate extraction while still allowing SST-derived answers.
        allow_ocr = bool(extractors.get("ocr", True))
        allow_vlm = bool(extractors.get("vlm", True))
        order_by = str(idle_cfg.get("order_by", "record_id") or "record_id").lower()
        checkpoint_mode = str(idle_cfg.get("checkpoint_mode", "record_id") or "record_id").lower()
        backfill_out_of_order = bool(idle_cfg.get("backfill_out_of_order", order_by == "ts_utc"))
        max_gpu = int(idle_cfg.get("max_concurrency_gpu", 1) or 0)
        batch_size = int(idle_cfg.get("batch_size", 4) or 1)
        if max_gpu <= 0:
            allow_vlm = False
        sst_cfg = self._config.get("processing", {}).get("sst", {})
        pipeline_enabled = bool(sst_cfg.get("enabled", True)) and self._pipeline is not None
        pipeline_allow_ocr = bool(sst_cfg.get("allow_ocr", allow_ocr))
        pipeline_allow_vlm = bool(sst_cfg.get("allow_vlm", allow_vlm))
        if max_gpu <= 0:
            pipeline_allow_vlm = False
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

        evidence_ids = self._ordered_evidence_ids(order_by)
        start_index = 0
        checkpoint = self._load_checkpoint() if persist_checkpoint and checkpoint_mode != "none" else None
        if checkpoint and checkpoint.last_record_id in evidence_ids:
            start_index = evidence_ids.index(checkpoint.last_record_id) + 1
        pending_ids = list(evidence_ids[start_index:])
        if backfill_out_of_order and start_index > 0:
            backlog: list[str] = []
            for record_id in evidence_ids[:start_index]:
                record = self._metadata.get(record_id, {})
                record_type = str(record.get("record_type", ""))
                if not record_type.startswith("evidence.capture."):
                    continue
                if self._needs_processing(
                    record_id,
                    record if isinstance(record, dict) else {},
                    allow_ocr,
                    allow_vlm,
                    pipeline_enabled,
                ):
                    backlog.append(record_id)
            if backlog:
                pending_ids = list(dict.fromkeys(backlog + pending_ids))

        processed_total = checkpoint.processed_total if checkpoint else 0
        last_record_id: str | None = None
        aborted = False
        ocr_providers = _capability_providers(self._ocr, "ocr.engine") if (allow_ocr and self._ocr is not None) else []
        vlm_providers = _capability_providers(self._vlm, "vision.extractor") if (allow_vlm and self._vlm is not None) else []
        items, last_record_id, aborted, _planned = self._collect_work_items(
            pending_ids=pending_ids,
            allow_ocr=allow_ocr,
            allow_vlm=allow_vlm,
            ocr_providers=ocr_providers,
            vlm_providers=vlm_providers,
            max_items=max_items,
            should_abort=should_abort,
            expired=_expired,
            pipeline_enabled=pipeline_enabled,
            stats=stats,
        )
        if items and not aborted and not _expired():
            max_cpu = int(idle_cfg.get("max_concurrency_cpu", 1) or 1)
            processed_total += self._batch_extract(
                items=items,
                kind="ocr",
                providers=ocr_providers,
                allow=allow_ocr,
                max_workers=max_cpu,
                batch_size=batch_size,
                should_abort=should_abort,
                expired=_expired,
                stats=stats,
                max_items=max_items,
            )
            processed_total += self._batch_extract(
                items=items,
                kind="vlm",
                providers=vlm_providers,
                allow=allow_vlm,
                max_workers=max_gpu if max_gpu > 0 else 1,
                batch_size=batch_size,
                should_abort=should_abort,
                expired=_expired,
                stats=stats,
                max_items=max_items,
            )
            pipeline = self._pipeline
            if pipeline_enabled and pipeline is not None and hasattr(pipeline, "process_record"):
                for item in items:
                    if not item.needs_pipeline:
                        continue
                    if should_abort and should_abort():
                        aborted = True
                        break
                    if _expired():
                        break
                    if max_items > 0 and stats.processed >= max_items:
                        break
                    try:
                        result = pipeline.process_record(
                            record_id=item.record_id,
                            record=item.record,
                            frame_bytes=item.frame_bytes,
                            allow_ocr=pipeline_allow_ocr,
                            allow_vlm=pipeline_allow_vlm,
                            should_abort=should_abort,
                            # Enforce both the per-run max_seconds_per_run deadline and any
                            # governor lease budget deadline, whichever is sooner.
                            deadline_ts=(
                                min(deadline_wall, budget_wall)
                                if budget_wall is not None
                                else deadline_wall
                            ),
                        )
                    except Exception as exc:
                        stats.errors += 1
                        if self._logger is not None:
                            self._logger.log("sst.pipeline_error", {"source_id": item.record_id, "error": str(exc)})
                        continue
                    if result.diagnostics and self._logger is not None:
                        self._logger.log(
                            "sst.pipeline_diagnostics",
                            {"source_id": item.record_id, "diagnostics": list(result.diagnostics)},
                        )
                    if result.diagnostics:
                        try:
                            runtime_cfg = self._config.get("runtime", {}) if isinstance(self._config, dict) else {}
                            enforce_cfg = runtime_cfg.get("mode_enforcement", {}) if isinstance(runtime_cfg, dict) else {}
                            fixture_override = bool(enforce_cfg.get("fixture_override", False))
                            if fixture_override:
                                data_dir = self._config.get("storage", {}).get("data_dir", "data")
                                diag_path = Path(str(data_dir)) / "logs" / "sst_diagnostics.jsonl"
                                diag_path.parent.mkdir(parents=True, exist_ok=True)
                                with diag_path.open("a", encoding="utf-8") as handle:
                                    handle.write(
                                        json.dumps(
                                            {"source_id": item.record_id, "diagnostics": list(result.diagnostics)},
                                            sort_keys=True,
                                        )
                                        + "\n"
                                    )
                        except Exception:
                            pass
                    stats.sst_runs += 1
                    stats.sst_heavy += int(result.heavy_ran)
                    stats.sst_tokens += int(result.ocr_tokens)
                    stats.processed += int(result.derived_records)
                    processed_total += int(result.derived_records)
            last_record_id = last_record_id or (items[-1].source_id if items else None)

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
