"""Idle-time processing for OCR/VLM extraction."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import zipfile
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from autocapture.core.hashing import TEXT_NORM_VERSION, hash_text, normalize_text
from autocapture_nx.kernel.derived_records import (
    build_derivation_edge,
    build_artifact_manifest,
    build_span_ref,
    build_text_record,
    artifact_manifest_id,
    derived_text_record_id,
    derivation_edge_id,
    model_identity,
)
from autocapture_nx.kernel.frame_evidence import ensure_frame_evidence
from autocapture.indexing.factory import build_indexes
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.kernel.model_output_records import (
    build_model_output_record,
    model_output_record_id,
)
from autocapture_nx.kernel.providers import capability_providers
from autocapture_nx.ingest.uia_obs_docs import (
    _ensure_frame_uia_docs,
    _frame_uia_expected_ids,
    _uia_extract_snapshot_dict,
)
from autocapture_nx.ingest.stage2_projection_docs import project_stage2_docs_for_frame
from autocapture_nx.storage.stage1_derived_store import build_stage1_overlay_store
from autocapture_nx.storage.facts_ndjson import append_fact_line
from autocapture.storage.retention import retention_eligibility_record_id
from autocapture.storage.stage1 import (
    mark_stage1_and_retention,
    mark_stage2_complete,
    stage1_complete_record_id,
    stage2_complete_record_id,
)


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
    records_planned: int = 0
    records_completed: int = 0
    pending_records: int = 0
    vlm_deferred: int = 0
    vlm_throttled: int = 0
    pipeline_deferred: int = 0
    stage1_complete_records: int = 0
    stage1_retention_marked_records: int = 0
    stage1_missing_retention_marker_count: int = 0
    stage1_backfill_scanned_records: int = 0
    stage1_backfill_marked_records: int = 0
    stage1_uia_docs_inserted: int = 0
    stage1_uia_frames_missing_count: int = 0
    stage2_projection_generated_docs: int = 0
    stage2_projection_inserted_docs: int = 0
    stage2_projection_generated_states: int = 0
    stage2_projection_inserted_states: int = 0
    stage2_projection_errors: int = 0
    stage2_complete_records: int = 0
    stage2_index_docs_target: int = 0
    stage2_index_docs_indexed: int = 0
    stage2_index_docs_missing: int = 0
    stage2_index_errors: int = 0
    stage2_index_stale_docs: int = 0
    stage2_index_freshness_lag_ms_last: float = 0.0
    stage2_index_freshness_lag_ms_max: float = 0.0


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
    needs_ocr: bool
    needs_vlm: bool
    needs_pipeline: bool
    allow_pipeline_vlm: bool
    deferred_vlm_from: str | None


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


def _legacy_derived_text_record_id(*, kind: str, run_id: str, provider_id: str, source_id: str) -> str:
    """Compatibility record id (pre-PERF-03) without model digest component."""

    provider_component = encode_record_id_component(provider_id)
    encoded_source = encode_record_id_component(source_id)
    return f"{run_id}/derived.text.{kind}/{provider_component}/{encoded_source}"


def _missing_derived_text(
    metadata: Any,
    *,
    kind: str,
    run_id: str,
    provider_id: str,
    source_id: str,
    config: dict[str, Any],
) -> tuple[bool, str]:
    """Return (missing, derived_id_to_use). Treat legacy ids as a hit."""

    derived_id = derived_text_record_id(kind=kind, run_id=run_id, provider_id=provider_id, source_id=source_id, config=config)
    if not _is_missing_metadata_record(metadata.get(derived_id)):
        return False, derived_id
    legacy_id = _legacy_derived_text_record_id(kind=kind, run_id=run_id, provider_id=provider_id, source_id=source_id)
    if not _is_missing_metadata_record(metadata.get(legacy_id)):
        return False, derived_id
    return True, derived_id


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
    # Mode B / sidecar contract commonly stores frames as raw PNG/JPEG bytes in
    # the media blob store, with no container metadata. Treat those as already
    # decoded frames.
    if not container_type:
        if blob.startswith(b"\x89PNG\r\n\x1a\n"):
            return blob
        if blob.startswith(b"\xff\xd8\xff"):
            return blob
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


def _resolve_data_dir(config: dict[str, Any] | None) -> str:
    if isinstance(config, dict):
        storage_cfg = config.get("storage", {}) if isinstance(config.get("storage", {}), dict) else {}
        candidate = str(storage_cfg.get("data_dir") or "").strip()
        if candidate:
            return candidate
    candidate = str(os.environ.get("AUTOCAPTURE_DATA_DIR") or "").strip()
    if candidate:
        return candidate
    return "data"


@lru_cache(maxsize=8)
def _legacy_media_roots(dataroot: str) -> tuple[str, ...]:
    root = os.path.abspath(str(dataroot or "data"))
    legacy_root = os.path.join(root, "legacy")
    if not os.path.isdir(legacy_root):
        return ()
    out: list[str] = []
    try:
        for name in os.listdir(legacy_root):
            if not str(name).startswith("media.orphan_runs."):
                continue
            candidate = os.path.join(legacy_root, str(name))
            if os.path.isdir(candidate):
                out.append(candidate)
    except OSError:
        return ()
    out.sort(reverse=True)
    return tuple(out)


@lru_cache(maxsize=4096)
def _legacy_root_for_media_prefix(dataroot: str, media_prefix: str) -> str:
    prefix = str(media_prefix or "").strip().strip("/")
    if not prefix:
        return ""
    for legacy_root in _legacy_media_roots(dataroot):
        try:
            if os.path.isdir(os.path.join(legacy_root, prefix)):
                return legacy_root
        except OSError:
            continue
    return ""


def _record_blob_path(record: dict[str, Any] | None) -> str:
    if not isinstance(record, dict):
        return ""
    for key in ("blob_path", "media_path", "media_relpath"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _candidate_blob_paths(*, dataroot: str, blob_path: str) -> list[str]:
    raw = str(blob_path or "").strip()
    if not raw:
        return []
    normalized = raw.replace("\\", "/").strip()
    if not normalized:
        return []
    if os.path.isabs(normalized):
        return [normalized]
    rel = normalized.lstrip("./")
    candidates = [os.path.join(dataroot, rel)]
    if rel.startswith("media/"):
        orphan_rel = rel[len("media/") :]
        prefix = orphan_rel.split("/", 1)[0]
        legacy_root = _legacy_root_for_media_prefix(dataroot, prefix)
        if legacy_root:
            candidates.append(os.path.join(legacy_root, orphan_rel))
    return candidates


def _read_blob_path(path: str) -> bytes | None:
    try:
        with open(path, "rb") as handle:
            data = handle.read()
        return data if data else None
    except OSError:
        return None


def _get_media_blob(
    store: Any,
    record_id: str,
    *,
    record: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> bytes | None:
    blob_path = _record_blob_path(record)
    if blob_path:
        dataroot = _resolve_data_dir(config)
        for candidate in _candidate_blob_paths(dataroot=dataroot, blob_path=blob_path):
            blob = _read_blob_path(candidate)
            if blob:
                return blob
        # Hypervisor sidecar contract publishes blob_path as the canonical frame location.
        # Avoid expensive store scans on misses when the path does not exist.
        return None
    if hasattr(store, "get"):
        blob = store.get(record_id)
        if isinstance(blob, (bytes, bytearray)) and blob:
            return bytes(blob)
    if hasattr(store, "get_stream"):
        handle = store.get_stream(record_id)
        if hasattr(handle, "read"):
            data = handle.read()
            if hasattr(handle, "close"):
                try:
                    handle.close()
                except Exception:
                    pass
            if isinstance(data, (bytes, bytearray)) and data:
                return bytes(data)
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
        self._stage1_store, self._stage1_derived = build_stage1_overlay_store(
            config=self._config,
            metadata=self._metadata,
            logger=self._logger,
        )
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
        return "system/state.idle.checkpoint"

    def _checkpoint_candidates(self) -> list[str]:
        candidates = [self._checkpoint_id()]
        # Legacy global checkpoint id used prior to strict evidence/schema gates.
        candidates.append("system/derived.idle.checkpoint")
        runtime_run_id = str(self._config.get("runtime", {}).get("run_id", "") or "").strip()
        if runtime_run_id:
            candidates.append(f"{runtime_run_id}/derived.idle.checkpoint")
        candidates.append("run/derived.idle.checkpoint")
        # Preserve order while deduping.
        out: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            out.append(candidate)
        return out

    def _checkpoint_store(self) -> Any | None:
        # Persist checkpoints in the stage1 derived overlay when available so
        # strict evidence schema validation on ingest metadata does not block
        # idle progress tracking.
        store = self._stage1_store
        if store is not None and hasattr(store, "get"):
            return store
        return self._metadata

    def _load_checkpoint(self) -> IdleCheckpoint | None:
        if self._checkpoint_loaded:
            return self._checkpoint
        self._checkpoint_loaded = True
        store = self._checkpoint_store()
        if store is None:
            return None
        for checkpoint_id in self._checkpoint_candidates():
            record = store.get(checkpoint_id, None)
            if not isinstance(record, dict):
                continue
            if str(record.get("record_type") or "") not in {"derived.idle.checkpoint", "system.idle.checkpoint"}:
                continue
            last_record_id = record.get("last_record_id")
            processed_total = int(record.get("processed_total", 0) or 0)
            updated = str(record.get("ts_utc") or "")
            if updated:
                self._checkpoint = IdleCheckpoint(last_record_id=str(last_record_id) if last_record_id else None, processed_total=processed_total, updated_utc=updated)
                break
        return self._checkpoint

    def _store_checkpoint(self, last_record_id: str, processed_total: int) -> None:
        store = self._checkpoint_store()
        if store is None:
            return
        ts_utc = datetime.now(timezone.utc).isoformat()
        run_id = str(self._config.get("runtime", {}).get("run_id", "") or "").strip() or "run"
        payload = {
            "record_type": "system.idle.checkpoint",
            "run_id": run_id,
            "ts_utc": ts_utc,
            "last_record_id": last_record_id,
            "processed_total": int(processed_total),
        }
        try:
            if hasattr(store, "put_replace"):
                try:
                    store.put_replace(self._checkpoint_id(), payload)
                except Exception:
                    store.put(self._checkpoint_id(), payload)
            else:
                store.put(self._checkpoint_id(), payload)
        except Exception as exc:
            if self._logger is not None:
                self._logger.log("idle.checkpoint_error", {"error": str(exc)})
            return
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
        record_ids = self._record_ids()
        canonical_ids = [record_id for record_id in record_ids if "/evidence.capture." in str(record_id)]
        if order_by != "ts_utc":
            # Canonical IDs are authoritative and avoid an expensive metadata.get()
            # call over every record in large DBs.
            if canonical_ids:
                canonical_ids.sort()
                return canonical_ids
            # Legacy compatibility fallback for datasets that predate canonical IDs.
            evidence_ids: list[str] = []
            for record_id in record_ids:
                record = self._metadata.get(record_id, {})
                record_type = str(record.get("record_type", ""))
                if record_type.startswith("evidence.capture."):
                    evidence_ids.append(record_id)
            evidence_ids.sort()
            return evidence_ids

        evidence: list[tuple[str, str | None]] = []
        if canonical_ids:
            for record_id in canonical_ids:
                record = self._metadata.get(record_id, {})
                ts = record.get("ts_start_utc") or record.get("ts_utc")
                evidence.append((record_id, ts))
        else:
            for record_id in record_ids:
                record = self._metadata.get(record_id, {})
                record_type = str(record.get("record_type", ""))
                if not record_type.startswith("evidence.capture."):
                    continue
                ts = record.get("ts_start_utc") or record.get("ts_utc")
                evidence.append((record_id, ts))
        evidence.sort(key=lambda item: (_ts_key(item[1]), item[0]))
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

    def _mark_stage1_retention(self, record_id: str, record: dict[str, Any], *, reason: str, stats: IdleProcessStats) -> None:
        if self._stage1_store is None:
            return
        try:
            self._ensure_stage1_uia_docs(record_id, record, stats=stats)
        except Exception:
            # Fail-open: stage1 marker pass will quarantine until docs are valid.
            pass
        try:
            result = mark_stage1_and_retention(
                self._stage1_store,
                record_id,
                record if isinstance(record, dict) else {},
                reason=reason,
                event_builder=self._events,
                logger=self._logger,
            )
            if bool(result.get("stage1_complete", False)):
                stats.stage1_complete_records += 1
                if bool(result.get("retention_missing", False)):
                    stats.stage1_missing_retention_marker_count += 1
                else:
                    stats.stage1_retention_marked_records += 1
                try:
                    self._ensure_stage2_projection(record_id, record, reason=reason, stats=stats)
                except Exception:
                    pass
        except Exception:
            pass

    def _ensure_stage2_projection(self, record_id: str, record: dict[str, Any], *, reason: str, stats: IdleProcessStats) -> None:
        if self._stage1_store is None:
            return
        if not isinstance(record, dict):
            return
        if str(record.get("record_type") or "") != "evidence.capture.frame":
            return
        projection: dict[str, Any]
        try:
            projection = project_stage2_docs_for_frame(
                self._stage1_store,
                source_record_id=str(record_id),
                frame_record=record,
                read_store=self._stage1_store,
                dry_run=False,
            )
        except Exception as exc:
            stats.stage2_projection_errors += 1
            if self._logger is not None:
                try:
                    self._logger.log(
                        "stage2.projection.error",
                        {"source_record_id": str(record_id), "error": f"{type(exc).__name__}:{exc}"},
                    )
                except Exception:
                    pass
            return
        stats.stage2_projection_generated_docs += int(projection.get("generated_docs", 0) or 0)
        stats.stage2_projection_inserted_docs += int(projection.get("inserted_docs", 0) or 0)
        stats.stage2_projection_generated_states += int(projection.get("generated_states", 0) or 0)
        stats.stage2_projection_inserted_states += int(projection.get("inserted_states", 0) or 0)
        stats.stage2_projection_errors += int(projection.get("errors", 0) or 0)
        self._refresh_stage2_projection_indexes(record=record, projection=projection, stats=stats)
        stage2_id, stage2_inserted = mark_stage2_complete(
            self._stage1_store,
            str(record_id),
            record,
            projection=projection,
            reason=reason,
            event_builder=self._events,
            logger=self._logger,
        )
        if stage2_id and stage2_inserted:
            marker = self._stage1_store.get(stage2_id, {})
            if isinstance(marker, dict) and bool(marker.get("complete", False)):
                stats.stage2_complete_records += 1

    def _refresh_stage2_projection_indexes(self, *, record: dict[str, Any], projection: dict[str, Any], stats: IdleProcessStats) -> None:
        if self._stage1_store is None:
            return
        doc_ids_any = projection.get("doc_ids")
        raw_doc_ids = doc_ids_any if isinstance(doc_ids_any, list) else []
        doc_ids = [str(item).strip() for item in raw_doc_ids if str(item).strip()]
        if not doc_ids:
            return
        stats.stage2_index_docs_target += int(len(doc_ids))
        ts_value = _ts_key(str(record.get("ts_utc") or record.get("ts_start_utc") or ""))
        if ts_value > 0:
            lag_ms = max(0.0, (time.time() - ts_value) * 1000.0)
            stats.stage2_index_freshness_lag_ms_last = float(round(lag_ms, 3))
            stats.stage2_index_freshness_lag_ms_max = float(round(max(float(stats.stage2_index_freshness_lag_ms_max), lag_ms), 3))
            idle_cfg = self._config.get("processing", {}).get("idle", {}) if isinstance(self._config, dict) else {}
            stale_threshold_ms = float(idle_cfg.get("stage2_index_stale_threshold_ms", 15000.0) or 15000.0)
            if lag_ms > stale_threshold_ms:
                stats.stage2_index_stale_docs += int(len(doc_ids))
        for doc_id in doc_ids:
            row = self._stage1_store.get(doc_id, None)
            if not isinstance(row, dict):
                stats.stage2_index_docs_missing += 1
                continue
            text = str(row.get("text") or "").strip()
            if not text:
                stats.stage2_index_docs_missing += 1
                continue
            backends, index_errors = self._index_text(doc_id, text)
            if backends > 0 and index_errors == 0:
                stats.stage2_index_docs_indexed += 1
            elif index_errors > 0:
                stats.stage2_index_errors += int(index_errors)

    def _ensure_stage1_uia_docs(self, record_id: str, record: dict[str, Any], *, stats: IdleProcessStats) -> None:
        if self._stage1_store is None:
            return
        if not isinstance(record, dict):
            return
        if str(record.get("record_type") or "") != "evidence.capture.frame":
            return
        plugins_cfg = self._config.get("plugins", {}) if isinstance(self._config, dict) else {}
        settings_cfg = plugins_cfg.get("settings", {}) if isinstance(plugins_cfg, dict) else {}
        uia_cfg = (
            settings_cfg.get("builtin.processing.sst.uia_context", {})
            if isinstance(settings_cfg, dict)
            else {}
        )
        allow_fallback = True
        require_hash_match = True
        if isinstance(uia_cfg, dict):
            allow_fallback = bool(uia_cfg.get("allow_latest_snapshot_fallback", True))
            require_hash_match = bool(uia_cfg.get("require_hash_match", True))
        dataroot = str(uia_cfg.get("dataroot") or "").strip() if isinstance(uia_cfg, dict) else ""
        storage_cfg = self._config.get("storage", {}) if isinstance(self._config, dict) else {}
        if not dataroot:
            dataroot = str(storage_cfg.get("data_dir") or "").strip()
        if not dataroot:
            dataroot = str(os.environ.get("AUTOCAPTURE_DATA_DIR") or "").strip()
        if not dataroot:
            dataroot = "data"
        status = _ensure_frame_uia_docs(
            self._stage1_store,
            source_record_id=str(record_id),
            record=record,
            dataroot=str(dataroot),
            snapshot_metadata=self._metadata,
            allow_latest_snapshot_fallback=bool(allow_fallback),
            require_hash_match=bool(require_hash_match),
        )
        stats.stage1_uia_docs_inserted += int(status.get("inserted", 0) or 0)
        if bool(status.get("required", False)) and not bool(status.get("ok", False)):
            stats.stage1_uia_frames_missing_count += 1

    def _has_stage1_uia_docs(self, record: dict[str, Any]) -> bool:
        if self._stage1_store is None:
            return True
        if not isinstance(record, dict):
            return True
        if str(record.get("record_type") or "") != "evidence.capture.frame":
            return True
        uia_ref_raw = record.get("uia_ref")
        uia_ref: dict[str, Any] = uia_ref_raw if isinstance(uia_ref_raw, dict) else {}
        uia_record_id = str(uia_ref.get("record_id") or "").strip()
        if not uia_record_id:
            return True
        expected_ids = _frame_uia_expected_ids(uia_record_id)
        missing = False
        for kind, doc_id in expected_ids.items():
            row = self._stage1_store.get(doc_id, None)
            if not (isinstance(row, dict) and str(row.get("record_type") or "") == kind):
                missing = True
                break
        if not missing:
            return True
        # Fail-open: if snapshot is unavailable we do not block stage1 completeness.
        metadata_get = getattr(self._metadata, "get", None)
        if not callable(metadata_get):
            return True
        try:
            snapshot_value = metadata_get(uia_record_id, None)
        except Exception:
            return True
        snapshot = _uia_extract_snapshot_dict(snapshot_value)
        if not isinstance(snapshot, dict):
            return True
        return False

    def _has_stage1_and_retention_markers(self, record_id: str, *, require_stage2: bool = True) -> bool:
        if self._stage1_store is None:
            return False
        stage1_marker = self._stage1_store.get(stage1_complete_record_id(record_id), None)
        retention_marker = self._stage1_store.get(retention_eligibility_record_id(record_id), None)
        if _is_missing_metadata_record(stage1_marker):
            return False
        if _is_missing_metadata_record(retention_marker):
            return False
        metadata_get = getattr(self._metadata, "get", None)
        if callable(metadata_get):
            try:
                record_raw = metadata_get(record_id, {})
            except Exception:
                record_raw = {}
        else:
            record_raw = {}
        record = record_raw if isinstance(record_raw, dict) else {}
        if str(record.get("record_type") or "") == "evidence.capture.frame":
            if not bool(retention_marker.get("stage1_contract_validated", False)):
                return False
            if bool(retention_marker.get("quarantine_pending", False)):
                return False
        if not self._has_stage1_uia_docs(record):
            return False
        if require_stage2 and str(record.get("record_type") or "") == "evidence.capture.frame":
            stage2_marker = self._stage1_store.get(stage2_complete_record_id(record_id), None)
            if _is_missing_metadata_record(stage2_marker):
                return False
            if not bool(stage2_marker.get("complete", False)):
                return False
        return True

    def _backfill_stage1_markers(
        self,
        *,
        evidence_ids: list[str],
        start_index: int,
        initial_scan_records: int,
        allow_ocr: bool,
        allow_vlm: bool,
        pipeline_enabled: bool,
        max_records: int,
        should_abort: Callable[[], bool] | None,
        expired: Callable[[], bool],
        stats: IdleProcessStats,
    ) -> int:
        if self._metadata is None:
            return 0
        if max_records <= 0:
            return 0
        safe_start = max(0, int(start_index))
        capped_start = min(safe_start, len(evidence_ids))
        if capped_start > 0:
            backfill_ids = list(reversed(evidence_ids[:capped_start]))
        else:
            cold_scan = int(initial_scan_records) if int(initial_scan_records) > 0 else int(max_records * 8)
            capped_scan = min(len(evidence_ids), max(1, cold_scan))
            if capped_scan <= 0:
                return 0
            backfill_ids = list(reversed(evidence_ids[-capped_scan:]))
        if not backfill_ids:
            return 0
        marked = 0
        scanned = 0
        # Work newest-first in the checkpointed prefix so recent unmarked frames
        # converge first; in cold-start mode scan a bounded newest tail.
        for record_id in backfill_ids:
            if should_abort and should_abort():
                break
            if expired():
                break
            if marked >= max_records:
                break
            record_raw = self._metadata.get(record_id, {})
            record = record_raw if isinstance(record_raw, dict) else {}
            record_type = str(record.get("record_type", ""))
            if not record_type.startswith("evidence.capture."):
                continue
            scanned += 1
            if self._has_stage1_and_retention_markers(record_id, require_stage2=True):
                continue
            stage1_marker = self._stage1_store.get(stage1_complete_record_id(record_id), None)
            retention_marker = self._stage1_store.get(retention_eligibility_record_id(record_id), None)
            has_stage1_core = not _is_missing_metadata_record(stage1_marker)
            has_retention_core = not _is_missing_metadata_record(retention_marker)
            if record_type == "evidence.capture.frame" and isinstance(retention_marker, dict):
                has_retention_core = has_retention_core and bool(retention_marker.get("stage1_contract_validated", False)) and not bool(
                    retention_marker.get("quarantine_pending", False)
                )
            if has_stage1_core and has_retention_core and record_type == "evidence.capture.frame":
                # Stage1 markers can pre-exist without obs.uia.* docs. Materialize docs
                # first, then recover Stage2 completion from normalized artifacts.
                self._ensure_stage1_uia_docs(record_id, record, stats=stats)
                has_stage1_retention = self._has_stage1_and_retention_markers(record_id, require_stage2=False)
            else:
                has_stage1_retention = False
            if has_stage1_retention:
                stage2_before = self._stage1_store.get(stage2_complete_record_id(record_id), None)
                had_stage2 = isinstance(stage2_before, dict) and bool(stage2_before.get("complete", False))
                self._ensure_stage2_projection(record_id, record, reason="stage1_backfill", stats=stats)
                stage2_after = self._stage1_store.get(stage2_complete_record_id(record_id), None)
                has_stage2 = isinstance(stage2_after, dict) and bool(stage2_after.get("complete", False))
                if has_stage2 and not had_stage2:
                    marked += 1
                continue
            if self._needs_processing(record_id, record, allow_ocr, allow_vlm, pipeline_enabled):
                continue
            had_stage1 = not _is_missing_metadata_record(self._metadata.get(stage1_complete_record_id(record_id), None))
            retention_marker = self._metadata.get(retention_eligibility_record_id(record_id), None)
            had_retention = not _is_missing_metadata_record(retention_marker)
            if str(record.get("record_type") or "") == "evidence.capture.frame" and isinstance(retention_marker, dict):
                had_retention = had_retention and bool(retention_marker.get("stage1_contract_validated", False)) and not bool(
                    retention_marker.get("quarantine_pending", False)
                )
            self._mark_stage1_retention(record_id, record, reason="stage1_backfill", stats=stats)
            has_stage1 = not _is_missing_metadata_record(self._metadata.get(stage1_complete_record_id(record_id), None))
            retention_after = self._metadata.get(retention_eligibility_record_id(record_id), None)
            has_retention = not _is_missing_metadata_record(retention_after)
            if str(record.get("record_type") or "") == "evidence.capture.frame" and isinstance(retention_after, dict):
                has_retention = has_retention and bool(retention_after.get("stage1_contract_validated", False)) and not bool(
                    retention_after.get("quarantine_pending", False)
                )
            if (has_stage1 and not had_stage1) or (has_retention and not had_retention):
                marked += 1
        stats.stage1_backfill_scanned_records += scanned
        stats.stage1_backfill_marked_records += marked
        return marked

    def _index_text(self, doc_id: str, text: str) -> tuple[int, int]:
        if not text:
            return 0, 0
        backends = 0
        errors = 0
        if self._lexical is not None:
            backends += 1
            try:
                if hasattr(self._lexical, "index_if_changed"):
                    self._lexical.index_if_changed(doc_id, text)  # type: ignore[attr-defined]
                else:
                    self._lexical.index(doc_id, text)
            except Exception as exc:
                errors += 1
                if self._logger is not None:
                    self._logger.log("index.lexical_error", {"doc_id": doc_id, "error": str(exc)})
        if self._vector is not None:
            backends += 1
            try:
                if hasattr(self._vector, "index_if_changed"):
                    self._vector.index_if_changed(doc_id, text)  # type: ignore[attr-defined]
                else:
                    self._vector.index(doc_id, text)
            except Exception as exc:
                errors += 1
                if self._logger is not None:
                    self._logger.log("index.vector_error", {"doc_id": doc_id, "error": str(exc)})
        return backends, errors

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
        # META-07: persist a content-addressed artifact manifest with lineage pointers.
        try:
            run_id = str(payload.get("run_id") or record_id.split("/", 1)[0])
            manifest_id = artifact_manifest_id(run_id, derived_id)
            artifact_hash = str(payload.get("payload_hash") or payload.get("content_hash") or "")
            derived_from = {
                "evidence_id": record_id,
                "evidence_hash": record.get("content_hash"),
                "model_digest": payload.get("model_digest"),
            }
            manifest = build_artifact_manifest(
                run_id=run_id,
                artifact_id=derived_id,
                artifact_sha256=artifact_hash,
                derived_from=derived_from,
                ts_utc=payload.get("ts_utc"),
            )
            if hasattr(self._metadata, "put_new"):
                try:
                    self._metadata.put_new(manifest_id, manifest)
                except Exception:
                    pass
            else:
                self._metadata.put(manifest_id, manifest)
        except Exception:
            pass
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
        intelligent_enabled: bool,
        defer_vlm_on_hash_repeat: bool,
        hash_repeat_window: int,
        should_abort: Callable[[], bool] | None,
        expired: Callable[[], bool],
        pipeline_enabled: bool,
        pipeline_required_for_completion: bool,
        stats: IdleProcessStats,
    ) -> tuple[list[_IdleWorkItem], str | None, bool, int]:
        metadata = self._metadata
        if metadata is None:
            return [], None, False, 0

        def _record_is_complete(candidate_record_id: str) -> bool:
            try:
                return bool(
                    self._has_stage1_and_retention_markers(
                        candidate_record_id,
                    )
                )
            except Exception:
                return False

        def _missing_counts_and_pipeline(candidate_record_id: str) -> tuple[int, int, bool]:
            ocr_missing_count = 0
            vlm_missing_count = 0
            if allow_ocr:
                for provider_id, _extractor in ocr_providers:
                    missing, _derived_id = _missing_derived_text(
                        metadata,
                        kind="ocr",
                        run_id=_derive_run_id(self._config, candidate_record_id),
                        provider_id=str(provider_id),
                        source_id=candidate_record_id,
                        config=self._config,
                    )
                    if missing:
                        ocr_missing_count += 1
            if allow_vlm:
                for provider_id, _extractor in vlm_providers:
                    missing, _derived_id = _missing_derived_text(
                        metadata,
                        kind="vlm",
                        run_id=_derive_run_id(self._config, candidate_record_id),
                        provider_id=str(provider_id),
                        source_id=candidate_record_id,
                        config=self._config,
                    )
                    if missing:
                        vlm_missing_count += 1
            needs_pipeline = False
            if pipeline_enabled:
                run_id = _derive_run_id(self._config, candidate_record_id)
                frame_component = encode_record_id_component(candidate_record_id)
                frame_id = f"{run_id}/derived.sst.frame/{frame_component}"
                if _is_missing_metadata_record(metadata.get(frame_id)):
                    needs_pipeline = True
            return ocr_missing_count, vlm_missing_count, needs_pipeline

        items: list[_IdleWorkItem] = []
        recent_hashes: deque[str] = deque(maxlen=max(1, int(hash_repeat_window)))
        recent_hash_set: set[str] = set()
        hash_vlm_anchor: dict[str, str] = {}
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
            # Stage1+retention(+stage2 when required) is authoritative for
            # background completion. If these markers already exist, avoid
            # expensive re-extraction and just advance checkpoint progress.
            if _record_is_complete(record_id):
                stats.records_completed += 1
                last_record_id = source_record_id
                continue
            ocr_missing_count, vlm_missing_count, needs_pipeline = _missing_counts_and_pipeline(record_id)
            missing_count = int(ocr_missing_count + vlm_missing_count)
            if missing_count == 0 and (not needs_pipeline or not pipeline_required_for_completion):
                self._mark_stage1_retention(record_id, record, reason="already_processed", stats=stats)
                if _record_is_complete(record_id):
                    stats.records_completed += 1
                last_record_id = source_record_id
                continue
            if max_items > 0 and planned >= max_items:
                break
            blob = _get_media_blob(self._media, record_id, record=record, config=self._config)
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
            if record_id != source_record_id:
                ocr_missing_count, vlm_missing_count, needs_pipeline = _missing_counts_and_pipeline(record_id)
                missing_count = int(ocr_missing_count + vlm_missing_count)
                if missing_count == 0 and (not needs_pipeline or not pipeline_required_for_completion):
                    self._mark_stage1_retention(record_id, record, reason="already_processed", stats=stats)
                    if _record_is_complete(record_id):
                        stats.records_completed += 1
                    last_record_id = source_record_id
                    continue
            content_hash = str(record.get("content_hash") or "").strip().lower()
            if (
                intelligent_enabled
                and defer_vlm_on_hash_repeat
                and vlm_missing_count > 0
                and content_hash
                and content_hash in recent_hash_set
            ):
                stats.vlm_deferred += 1
                deferred_vlm_from = hash_vlm_anchor.get(content_hash)
                vlm_missing_count = 0
            else:
                deferred_vlm_from = None
                if content_hash and vlm_missing_count > 0 and content_hash not in hash_vlm_anchor:
                    hash_vlm_anchor[content_hash] = record_id
            if content_hash:
                if len(recent_hashes) == recent_hashes.maxlen and recent_hashes:
                    evicted = recent_hashes[0]
                else:
                    evicted = ""
                recent_hashes.append(content_hash)
                recent_hash_set.add(content_hash)
                if evicted and evicted not in recent_hashes:
                    recent_hash_set.discard(evicted)
            needs_ocr = ocr_missing_count > 0
            needs_vlm = vlm_missing_count > 0
            if missing_count == 0 and (not needs_pipeline or not pipeline_required_for_completion):
                self._mark_stage1_retention(record_id, record, reason="already_processed", stats=stats)
                if _record_is_complete(record_id):
                    stats.records_completed += 1
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
                    needs_ocr=needs_ocr,
                    needs_vlm=needs_vlm,
                    needs_pipeline=needs_pipeline,
                    allow_pipeline_vlm=needs_vlm,
                    deferred_vlm_from=deferred_vlm_from,
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
        max_records: int = 0,
    ) -> int:
        if not items or not allow or self._metadata is None:
            return 0
        processed = 0
        scheduled_records: set[str] = set()

        def _placeholder_payload(*, item: _IdleWorkItem, provider_id: str, status: str, response: Any) -> dict[str, Any]:
            normalized = normalize_text("")
            identity = model_identity(kind, provider_id, self._config)
            payload: dict[str, Any] = {
                "schema_version": 1,
                "record_type": f"derived.text.{kind}",
                "run_id": (item.record.get("run_id") or item.record_id.split("/", 1)[0]),
                "ts_utc": item.ts_utc,
                "text": "",
                "text_normalized": normalized,
                "text_norm_version": TEXT_NORM_VERSION,
                "source_id": item.record_id,
                "parent_evidence_id": item.record_id,
                "span_ref": build_span_ref(item.record, item.record_id),
                "method": kind,
                "provider_id": provider_id,
                "model_id": identity["model_id"],
                "model_digest": identity["model_digest"],
                "model_provider": identity["model_provider"],
                "parameters": identity["parameters"],
                "content_hash": hash_text(normalized),
                "extraction_status": status,
            }
            if isinstance(response, dict):
                backend = str(response.get("backend") or "").strip()
                model_error = str(response.get("model_error") or "").strip()
                if backend:
                    payload["extractor_backend"] = backend
                if model_error:
                    payload["extractor_model_error"] = model_error
            return payload

        for provider_id, extractor in providers:
            if should_abort and should_abort():
                break
            if expired():
                break
            tasks: list[tuple[_IdleWorkItem, str]] = []
            for item in items:
                if kind == "ocr" and not bool(item.needs_ocr):
                    continue
                if kind == "vlm" and not bool(item.needs_vlm):
                    continue
                if max_records > 0 and item.record_id not in scheduled_records and len(scheduled_records) >= max_records:
                    if kind == "vlm":
                        stats.vlm_throttled += 1
                    continue
                missing, derived_id = _missing_derived_text(
                    self._metadata,
                    kind=kind,
                    run_id=item.run_id,
                    provider_id=str(provider_id),
                    source_id=item.record_id,
                    config=self._config,
                )
                if missing:
                    tasks.append((item, derived_id))
                    if max_records > 0:
                        scheduled_records.add(item.record_id)
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
                    stop_after_item = expired()
                    if max_items > 0 and stats.processed >= max_items:
                        return processed
                    if response is None:
                        stats.errors += 1
                        payload = _placeholder_payload(
                            item=item,
                            provider_id=str(provider_id),
                            status="error",
                            response=None,
                        )
                        payload["extractor_error"] = "null_response"
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
                        if stop_after_item or expired():
                            return processed
                        continue
                    texts = _response_texts(response)
                    if not texts:
                        if kind == "vlm" and self._logger is not None and isinstance(response, dict):
                            try:
                                self._logger.log(
                                    "idle.vlm_empty_response",
                                    {
                                        "provider_id": str(provider_id),
                                        "source_id": item.record_id,
                                        "backend": str(response.get("backend") or ""),
                                        "model_error": str(response.get("model_error") or ""),
                                    },
                                )
                            except Exception:
                                pass
                        payload = _placeholder_payload(
                            item=item,
                            provider_id=str(provider_id),
                            status="empty",
                            response=response,
                        )
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
                        if stop_after_item or expired():
                            return processed
                        continue
                    text = "\n\n".join(texts)
                    text_payload = build_text_record(
                        kind=kind,
                        text=text,
                        source_id=item.record_id,
                        source_record=item.record,
                        provider_id=provider_id,
                        config=self._config,
                        ts_utc=item.ts_utc,
                    )
                    if not text_payload:
                        if stop_after_item or expired():
                            return processed
                        continue
                    stored = self._store_derived_text(
                        derived_id=derived_id,
                        payload=text_payload,
                        record_id=item.record_id,
                        record=item.record,
                        kind=kind,
                        stats=stats,
                    )
                    if stored:
                        processed += 1
                        # Canonical per-model output record + append-only facts sink.
                        try:
                            out_payload = build_model_output_record(
                                modality=kind,
                                provider_id=str(provider_id),
                                response=response,
                                extracted_text=str(payload.get("text") or ""),
                                source_id=item.record_id,
                                source_record=item.record,
                                config=self._config,
                                ts_utc=item.ts_utc,
                            )
                            out_id = model_output_record_id(
                                modality=kind,
                                run_id=item.run_id,
                                provider_id=str(provider_id),
                                source_id=item.record_id,
                                model_digest=str(out_payload.get("model_digest") or payload.get("model_digest") or ""),
                            )
                            if _is_missing_metadata_record(self._metadata.get(out_id)):
                                if hasattr(self._metadata, "put_new"):
                                    try:
                                        self._metadata.put_new(out_id, out_payload)
                                    except Exception:
                                        pass
                                else:
                                    self._metadata.put(out_id, out_payload)
                            _ = append_fact_line(self._config, rel_path="model_outputs.ndjson", payload=out_payload)
                        except Exception:
                            pass
                    if stop_after_item or expired():
                        return processed
        return processed

    def _materialize_deferred_vlm(
        self,
        *,
        items: list[_IdleWorkItem],
        providers: list[tuple[str, Any]],
        stats: IdleProcessStats,
        max_items: int,
    ) -> int:
        if self._metadata is None or not items or not providers:
            return 0
        copied = 0
        for item in items:
            source_id = str(item.deferred_vlm_from or "").strip()
            if not source_id:
                continue
            for provider_id, _extractor in providers:
                if max_items > 0 and stats.processed >= max_items:
                    return copied
                missing_target, target_derived_id = _missing_derived_text(
                    self._metadata,
                    kind="vlm",
                    run_id=item.run_id,
                    provider_id=str(provider_id),
                    source_id=item.record_id,
                    config=self._config,
                )
                if not missing_target:
                    continue
                missing_source, source_derived_id = _missing_derived_text(
                    self._metadata,
                    kind="vlm",
                    run_id=_derive_run_id(self._config, source_id),
                    provider_id=str(provider_id),
                    source_id=source_id,
                    config=self._config,
                )
                if missing_source:
                    continue
                source_payload = self._metadata.get(source_derived_id, {})
                if not isinstance(source_payload, dict):
                    continue
                text = str(source_payload.get("text") or "").strip()
                if not text:
                    continue
                payload = build_text_record(
                    kind="vlm",
                    text=text,
                    source_id=item.record_id,
                    source_record=item.record,
                    provider_id=str(provider_id),
                    config=self._config,
                    ts_utc=item.ts_utc,
                )
                if not payload:
                    continue
                stored = self._store_derived_text(
                    derived_id=target_derived_id,
                    payload=payload,
                    record_id=item.record_id,
                    record=item.record,
                    kind="vlm",
                    stats=stats,
                )
                if stored:
                    copied += 1
        return copied

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
        intelligent_cfg = idle_cfg.get("intelligent_batch", {}) if isinstance(idle_cfg.get("intelligent_batch", {}), dict) else {}
        intelligent_enabled = bool(intelligent_cfg.get("enabled", False))
        defer_vlm_on_hash_repeat = bool(intelligent_cfg.get("defer_vlm_on_hash_repeat", True))
        hash_repeat_window = max(1, int(intelligent_cfg.get("hash_repeat_window", 8) or 8))
        max_vlm_records_per_run = max(0, int(intelligent_cfg.get("max_vlm_records_per_run", 0) or 0))
        max_pipeline_records_per_run = max(0, int(intelligent_cfg.get("max_pipeline_records_per_run", 0) or 0))
        stage1_backfill_cfg = idle_cfg.get("stage1_marker_backfill", {}) if isinstance(idle_cfg.get("stage1_marker_backfill", {}), dict) else {}
        stage1_backfill_enabled = bool(stage1_backfill_cfg.get("enabled", True))
        default_stage1_backfill_max = max(256, int(max_items * 4) if max_items > 0 else 512)
        stage1_backfill_max_records = max(0, int(stage1_backfill_cfg.get("max_records_per_run", default_stage1_backfill_max) or 0))
        default_stage1_backfill_initial_scan = max(stage1_backfill_max_records * 4, 1024)
        stage1_backfill_initial_scan_records = max(
            1,
            int(stage1_backfill_cfg.get("initial_scan_records", default_stage1_backfill_initial_scan) or default_stage1_backfill_initial_scan),
        )
        if max_gpu <= 0:
            allow_vlm = False
        sst_cfg = self._config.get("processing", {}).get("sst", {})
        pipeline_enabled = bool(sst_cfg.get("enabled", True)) and callable(getattr(self._pipeline, "process_record", None))
        pipeline_allow_ocr = bool(sst_cfg.get("allow_ocr", allow_ocr))
        pipeline_allow_vlm = bool(sst_cfg.get("allow_vlm", allow_vlm))
        pipeline_required_cfg = idle_cfg.get("pipeline_required_for_stage1", None)
        # Stage1 completion semantics depend on SST/derived records (including UIA
        # linkage docs). Default to requiring pipeline completion unless explicitly
        # disabled in config.
        if pipeline_required_cfg is None:
            pipeline_required_for_completion = bool(pipeline_enabled)
        else:
            pipeline_required_for_completion = bool(pipeline_required_cfg)
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
        collect_budget_fraction = float(idle_cfg.get("collect_budget_fraction", 0.4) or 0.4)
        if collect_budget_fraction < 0.1:
            collect_budget_fraction = 0.1
        if collect_budget_fraction > 0.95:
            collect_budget_fraction = 0.95
        collect_budget_min_ms = float(idle_cfg.get("collect_min_ms", 200.0) or 200.0)
        if collect_budget_min_ms < 0.0:
            collect_budget_min_ms = 0.0
        collect_budget_mono: float | None = None

        def _expired() -> bool:
            now = time.monotonic()
            if now >= deadline_mono:
                return True
            if budget_mono is not None and now >= budget_mono:
                return True
            return False

        def _collect_expired() -> bool:
            now = time.monotonic()
            if now >= deadline_mono:
                return True
            if collect_budget_mono is not None and now >= collect_budget_mono:
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
        stats.pending_records = int(len(pending_ids))
        if budget_mono is not None:
            now = time.monotonic()
            remaining_budget_s = max(0.0, budget_mono - now)
            if remaining_budget_s <= 0.0:
                collect_budget_mono = now
            else:
                collect_window_s = max(collect_budget_min_ms / 1000.0, remaining_budget_s * collect_budget_fraction)
                collect_budget_mono = min(budget_mono, now + collect_window_s)

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
            intelligent_enabled=intelligent_enabled,
            defer_vlm_on_hash_repeat=defer_vlm_on_hash_repeat,
            hash_repeat_window=hash_repeat_window,
                should_abort=should_abort,
                expired=_collect_expired,
                pipeline_enabled=pipeline_enabled,
                pipeline_required_for_completion=pipeline_required_for_completion,
                stats=stats,
            )
        stats.records_planned = int(len(items))
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
                max_records=max_vlm_records_per_run,
            )
            processed_total += self._materialize_deferred_vlm(
                items=items,
                providers=vlm_providers,
                stats=stats,
                max_items=max_items,
            )
            pipeline = self._pipeline
            if pipeline_enabled and pipeline is not None and hasattr(pipeline, "process_record"):
                pipeline_processed = 0
                for item in items:
                    if not item.needs_pipeline:
                        continue
                    if max_pipeline_records_per_run > 0 and pipeline_processed >= max_pipeline_records_per_run:
                        stats.pipeline_deferred += 1
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
                            allow_vlm=bool(pipeline_allow_vlm and item.allow_pipeline_vlm),
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
                    pipeline_processed += 1
            for item in items:
                if self._needs_processing(
                    item.record_id,
                    item.record if isinstance(item.record, dict) else {},
                    allow_ocr,
                    allow_vlm,
                    pipeline_enabled if pipeline_required_for_completion else False,
                ):
                    continue
                self._mark_stage1_retention(item.record_id, item.record, reason="idle_processed", stats=stats)
                if self._has_stage1_and_retention_markers(
                    item.record_id,
                ):
                    stats.records_completed += 1
                last_record_id = last_record_id or (items[-1].source_id if items else None)
        if (
            stage1_backfill_enabled
            and stage1_backfill_max_records > 0
            and not aborted
            and not _expired()
        ):
            self._backfill_stage1_markers(
                evidence_ids=evidence_ids,
                start_index=start_index,
                initial_scan_records=stage1_backfill_initial_scan_records,
                allow_ocr=allow_ocr,
                allow_vlm=allow_vlm,
                pipeline_enabled=pipeline_enabled if pipeline_required_for_completion else False,
                max_records=stage1_backfill_max_records,
                should_abort=should_abort,
                expired=_expired,
                stats=stats,
            )

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
