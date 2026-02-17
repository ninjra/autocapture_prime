"""ChatGPT (Edge) transcript export helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import zipfile
from bisect import bisect_right
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Iterator

from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.kernel.derived_records import extract_text_payload
from autocapture_nx.kernel.providers import capability_providers

_CHATGPT_RE = re.compile(r"(chatgpt|openai)", re.IGNORECASE)
_EDGE_RE = re.compile(r"msedge", re.IGNORECASE)
_FRAME_RE = re.compile(r"^frame_(\d+)\.(jpg|jpeg|png)$", re.IGNORECASE)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def resolve_export_root(config: dict[str, Any]) -> Path:
    env_root = str(os.getenv("KERNEL_AUTOCAPTURE_EXPORT_ROOT") or "").strip()
    if env_root:
        root = Path(env_root)
    else:
        env_data_root = str(os.getenv("KERNEL_AUTOCAPTURE_DATA_ROOT") or "").strip()
        if os.name == "nt" and env_data_root:
            root = Path(env_data_root).parent / "exports"
        else:
            root = Path.cwd() / "data" / "exports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _journal_path(config: dict[str, Any]) -> Path:
    storage_cfg = config.get("storage", {}) if isinstance(config, dict) else {}
    data_dir = storage_cfg.get("data_dir", "data") if isinstance(storage_cfg, dict) else "data"
    return Path(str(data_dir)) / "journal.ndjson"


def iter_capture_segments(
    journal_path: Path,
    *,
    since_ts: str | None = None,
    max_segments: int | None = None,
) -> Iterator[dict[str, Any]]:
    since_dt = _parse_ts(since_ts)
    yielded = 0
    with journal_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if str(item.get("event_type") or "") != "capture.segment":
                continue
            payload = item.get("payload")
            if not isinstance(payload, dict):
                continue
            segment_id = payload.get("segment_id") or item.get("event_id")
            if not segment_id:
                continue
            segment_ts = (
                payload.get("ts_utc")
                or payload.get("ts_start_utc")
                or payload.get("ts_end_utc")
                or item.get("ts_utc")
            )
            parsed = _parse_ts(str(segment_ts) if segment_ts is not None else None)
            if since_dt is not None and (parsed is None or parsed < since_dt):
                continue
            entry = dict(payload)
            entry["segment_id"] = str(segment_id)
            entry["_journal_event_id"] = str(item.get("event_id") or "")
            entry["_journal_ts_utc"] = str(item.get("ts_utc") or "")
            yield entry
            yielded += 1
            if max_segments is not None and yielded >= max(0, int(max_segments)):
                return


def load_window_index(metadata_store: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if metadata_store is None or not hasattr(metadata_store, "keys") or not hasattr(metadata_store, "get"):
        return rows
    for record_id in metadata_store.keys():
        try:
            record = metadata_store.get(record_id, None)
        except Exception:
            continue
        if not isinstance(record, dict):
            continue
        if str(record.get("record_type") or "") != "evidence.window.meta":
            continue
        window = record.get("window") if isinstance(record.get("window"), dict) else {}
        title = str(window.get("title") or "")
        process_path = str(window.get("process_path") or "")
        ts_utc = str(record.get("ts_utc") or "")
        ts = _parse_ts(ts_utc)
        if ts is None:
            continue
        rows.append(
            {
                "record_id": str(record_id),
                "ts_utc": ts_utc,
                "_ts": ts,
                "window_title": title,
                "process_path": process_path,
            }
        )
    rows.sort(key=lambda row: (row["_ts"], row["record_id"]))
    return rows


def match_window_for_segment(
    window_index: list[dict[str, Any]],
    segment_ts_utc: str | None,
    *,
    lookback_s: int = 10,
) -> dict[str, Any] | None:
    segment_ts = _parse_ts(segment_ts_utc)
    if segment_ts is None or not window_index:
        return None
    ts_values = [row["_ts"] for row in window_index]
    idx = bisect_right(ts_values, segment_ts) - 1
    if idx < 0:
        return None
    candidate = window_index[idx]
    delta = (segment_ts - candidate["_ts"]).total_seconds()
    if delta < 0 or delta > max(0, int(lookback_s)):
        return None
    return candidate


def iter_selected_frames(zip_bytes: bytes, frame_count: int) -> Iterator[tuple[str, bytes]]:
    with zipfile.ZipFile(BytesIO(zip_bytes), "r") as archive:
        by_idx: dict[int, str] = {}
        for name in archive.namelist():
            base = Path(name).name
            match = _FRAME_RE.match(base)
            if not match:
                continue
            idx = int(match.group(1))
            by_idx[idx] = name
        if not by_idx:
            return
        if frame_count > 0:
            last = max(0, int(frame_count) - 1)
        else:
            last = max(by_idx.keys())
        mid = max(0, last // 2)
        wanted: list[int] = []
        for idx in (0, mid, last):
            if idx not in wanted:
                wanted.append(idx)
        for idx in wanted:
            name = by_idx.get(idx)
            if not name:
                continue
            try:
                yield (Path(name).name, archive.read(name))
            except Exception:
                continue


def extract_text(system: Any, image_bytes: bytes) -> str:
    if system is None or not hasattr(system, "get"):
        return ""
    ocr = None
    try:
        ocr = system.get("ocr.engine")
    except Exception:
        ocr = None
    if ocr is None:
        return ""
    for _provider_id, extractor in capability_providers(ocr, "ocr.engine"):
        if extractor is None or not hasattr(extractor, "extract"):
            continue
        try:
            payload = extractor.extract(image_bytes)
        except Exception:
            continue
        text = _normalize_text(extract_text_payload(payload))
        if text:
            return text
    return ""


def sanitize_text(system: Any, text: str) -> tuple[str, list[dict[str, Any]], bool, str | None]:
    if system is None or not hasattr(system, "get"):
        return text, [], True, None
    sanitizer = None
    try:
        sanitizer = system.get("privacy.egress_sanitizer")
    except Exception:
        sanitizer = None
    if sanitizer is None or not hasattr(sanitizer, "sanitize_text"):
        return text, [], True, None
    try:
        output = sanitizer.sanitize_text(text, scope="chatgpt")
    except Exception:
        return "", [], False, "sanitize_error"
    sanitized = str(output.get("text") or "")
    glossary = output.get("glossary")
    if not isinstance(glossary, list):
        glossary = []
    leak_ok = True
    if hasattr(sanitizer, "leak_check"):
        try:
            leak_ok = bool(
                sanitizer.leak_check(
                    {
                        "text": sanitized,
                        "_tokens": output.get("tokens") if isinstance(output, dict) else {},
                        "_glossary": glossary,
                    }
                )
            )
        except Exception:
            leak_ok = False
    if not leak_ok:
        return "", glossary, False, "leak_check_failed"
    return sanitized, glossary, True, None


def read_prev_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        if size <= 0:
            return None
        block = 4096
        data = bytearray()
        pos = size
        while pos > 0:
            read_size = min(block, pos)
            pos -= read_size
            handle.seek(pos)
            data[:0] = handle.read(read_size)
            if b"\n" in data:
                break
    for raw in reversed(bytes(data).splitlines()):
        line = raw.decode("utf-8", errors="ignore").strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        value = str(payload.get("entry_hash") or "").strip()
        if value:
            return value
    return None


def append_export_line(path: Path, obj: dict[str, Any], prev_hash: str | None) -> str:
    payload = dict(obj)
    payload["prev_hash"] = prev_hash
    payload.pop("entry_hash", None)
    canonical = dumps(payload)
    entry_hash = hashlib.sha256((canonical + (prev_hash or "")).encode("utf-8")).hexdigest()
    payload["entry_hash"] = entry_hash
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{dumps(payload)}\n")
    return entry_hash


def _session_id(window_title: str, process_path: str) -> str:
    seed = f"{window_title}\n{process_path}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _marker_write(metadata_store: Any, key: str, value: dict[str, Any]) -> None:
    if metadata_store is None:
        return
    if hasattr(metadata_store, "put_replace"):
        metadata_store.put_replace(key, value)
        return
    if hasattr(metadata_store, "put"):
        metadata_store.put(key, value)
        return
    if hasattr(metadata_store, "put_new"):
        try:
            metadata_store.put_new(key, value)
        except Exception:
            pass


def run_export_pass(
    system: Any,
    *,
    max_segments: int | None = None,
    since_ts: str | None = None,
) -> dict[str, Any]:
    config = getattr(system, "config", {})
    export_root = resolve_export_root(config if isinstance(config, dict) else {})
    export_path = export_root / "chatgpt_transcripts.ndjson"
    journal_path = _journal_path(config if isinstance(config, dict) else {})
    result: dict[str, Any] = {
        "ok": True,
        "export_root": str(export_root),
        "export_path": str(export_path),
        "journal_path": str(journal_path),
        "segments_scanned": 0,
        "segments_exported": 0,
        "segments_skipped_already_exported": 0,
        "segments_skipped_no_window": 0,
        "segments_skipped_non_edge": 0,
        "segments_skipped_no_media": 0,
        "segments_skipped_non_zip": 0,
        "segments_skipped_no_frames": 0,
        "segments_skipped_no_text": 0,
        "lines_appended": 0,
        "errors": [],
        "finished_utc": "",
        "duration_ms": 0,
    }
    started = time.perf_counter()
    if not journal_path.exists():
        result["finished_utc"] = _utc_now()
        result["warning"] = "journal_missing"
        result["duration_ms"] = int(max(0.0, (time.perf_counter() - started) * 1000.0))
        return result

    metadata = system.get("storage.metadata") if hasattr(system, "get") else None
    media = system.get("storage.media") if hasattr(system, "get") else None
    if metadata is None or media is None:
        result["ok"] = False
        result["error"] = "missing_storage_capabilities"
        result["finished_utc"] = _utc_now()
        result["duration_ms"] = int(max(0.0, (time.perf_counter() - started) * 1000.0))
        return result

    window_index = load_window_index(metadata)
    prev_hash = read_prev_hash(export_path)
    max_segments_val = int(max_segments) if max_segments is not None else None
    if max_segments_val is not None and max_segments_val <= 0:
        max_segments_val = None

    for segment in iter_capture_segments(journal_path, since_ts=since_ts, max_segments=max_segments_val):
        result["segments_scanned"] = int(result["segments_scanned"]) + 1
        segment_id = str(segment.get("segment_id") or "")
        marker_key = f"export.chatgpt.{segment_id}"
        marker_existing = None
        try:
            marker_existing = metadata.get(marker_key, None) if hasattr(metadata, "get") else None
        except Exception:
            marker_existing = None
        if marker_existing:
            result["segments_skipped_already_exported"] = int(result["segments_skipped_already_exported"]) + 1
            continue

        segment_ts = str(segment.get("ts_utc") or segment.get("ts_start_utc") or "")
        window = match_window_for_segment(window_index, segment_ts, lookback_s=10)
        if window is None:
            result["segments_skipped_no_window"] = int(result["segments_skipped_no_window"]) + 1
            continue
        process_path = str(window.get("process_path") or "")
        window_title = str(window.get("window_title") or "")
        if not _EDGE_RE.search(process_path):
            result["segments_skipped_non_edge"] = int(result["segments_skipped_non_edge"]) + 1
            continue
        high_confidence = bool(_CHATGPT_RE.search(window_title))

        blob = None
        try:
            blob = media.get(segment_id, None) if hasattr(media, "get") else None
        except Exception as exc:
            result["errors"].append(f"media_read_error:{segment_id}:{type(exc).__name__}")
        if not isinstance(blob, (bytes, bytearray)) or not blob:
            result["segments_skipped_no_media"] = int(result["segments_skipped_no_media"]) + 1
            continue

        frame_count = int(segment.get("frame_count") or 0)
        try:
            frames = list(iter_selected_frames(bytes(blob), frame_count))
        except zipfile.BadZipFile:
            result["segments_skipped_non_zip"] = int(result["segments_skipped_non_zip"]) + 1
            continue
        except Exception as exc:
            result["errors"].append(f"zip_error:{segment_id}:{type(exc).__name__}")
            result["segments_skipped_non_zip"] = int(result["segments_skipped_non_zip"]) + 1
            continue
        if not frames:
            result["segments_skipped_no_frames"] = int(result["segments_skipped_no_frames"]) + 1
            continue

        entry_hashes: list[str] = []
        for frame_name, frame_bytes in frames:
            text = _normalize_text(extract_text(system, frame_bytes))
            if not text:
                continue
            text_lower = text.lower()
            if len(text) < 40 and "chatgpt" not in text_lower and "openai" not in text_lower:
                continue
            if not high_confidence and "chatgpt" not in text_lower and "openai" not in text_lower:
                continue
            sanitized_text, glossary, _leak_ok, export_notice = sanitize_text(system, text)
            payload = {
                "schema_version": 1,
                "entry_id": f"chatgpt:edge:session:{_session_id(window_title, process_path)}",
                "ts_utc": _utc_now(),
                "source": {
                    "browser": "msedge",
                    "app": "chatgpt",
                    "window_title": window_title,
                    "process_path": process_path,
                },
                "segment_id": segment_id,
                "frame_name": frame_name,
                "text": sanitized_text,
                "glossary": glossary,
            }
            if export_notice:
                payload["export_notice"] = export_notice
            prev_hash = append_export_line(export_path, payload, prev_hash)
            entry_hashes.append(prev_hash)
            result["lines_appended"] = int(result["lines_appended"]) + 1

        if entry_hashes:
            result["segments_exported"] = int(result["segments_exported"]) + 1
            marker_value = {
                "schema_version": 1,
                "record_type": "derived.export.chatgpt.segment",
                "segment_id": segment_id,
                "exported_at": _utc_now(),
                "entry_hashes": entry_hashes,
            }
            try:
                _marker_write(metadata, marker_key, marker_value)
            except Exception as exc:
                result["errors"].append(f"marker_write_error:{segment_id}:{type(exc).__name__}")
        else:
            result["segments_skipped_no_text"] = int(result["segments_skipped_no_text"]) + 1

    result["finished_utc"] = _utc_now()
    result["duration_ms"] = int(max(0.0, (time.perf_counter() - started) * 1000.0))
    return result

