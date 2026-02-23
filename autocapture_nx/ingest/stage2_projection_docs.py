"""Normalized Stage2 projection docs from frame/UIA metadata."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.hashing import sha256_text
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.ingest.uia_obs_docs import _frame_uia_expected_ids
from autocapture_nx.ingest.uia_obs_docs import _uia_extract_snapshot_dict
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.observation_graph.plugin import ObservationGraphPlugin


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _run_id_for_frame(source_record_id: str, frame: dict[str, Any]) -> str:
    run_id = str(frame.get("run_id") or "").strip()
    if run_id:
        return run_id
    if "/" in source_record_id:
        return source_record_id.split("/", 1)[0]
    return "run"


def _ts_for_frame(frame: dict[str, Any]) -> str:
    for key in ("ts_utc", "ts_start_utc", "ts_end_utc"):
        value = str(frame.get(key) or "").strip()
        if value:
            return value
    return _utc_now()


def _normalized_bbox(raw: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x1, y1, x2, y2 = (int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3]))
    except Exception:
        return None
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _line(text: str, bbox: tuple[int, int, int, int] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"text": str(text)}
    if isinstance(bbox, tuple):
        row["bbox"] = [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]
    return row


def _snapshot_lines(snapshot: dict[str, Any], *, max_nodes: int = 256) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    window = snapshot.get("window") if isinstance(snapshot.get("window"), dict) else {}
    window_title = str(window.get("title") or "").strip()
    process_path = str(window.get("process_path") or "").strip()
    window_pid = _safe_int(window.get("pid"), default=0)
    if window_title:
        lines.append(_line(f"window_title {window_title}"))
    if process_path:
        lines.append(_line(f"window_process_path {process_path}"))
    if window_pid > 0:
        lines.append(_line(f"window_pid {window_pid}"))

    count = 0
    for section in ("focus_path", "context_peers", "operables"):
        raw_nodes = snapshot.get(section) if isinstance(snapshot.get(section), list) else []
        for idx, node in enumerate(raw_nodes, start=1):
            if count >= max(1, int(max_nodes)):
                return lines
            if not isinstance(node, dict):
                continue
            name = str(node.get("name") or "").strip()
            role = str(node.get("role") or "").strip()
            aid = str(node.get("aid") or "").strip()
            klass = str(node.get("class") or "").strip()
            if not (name or role or aid or klass):
                continue
            text_parts = [f"uia.{section}.{idx}"]
            if name:
                text_parts.append(f"name={name}")
            if role:
                text_parts.append(f"role={role}")
            if aid:
                text_parts.append(f"aid={aid}")
            if klass:
                text_parts.append(f"class={klass}")
            bbox = _normalized_bbox(node.get("rect"))
            lines.append(_line("; ".join(text_parts), bbox=bbox))
            count += 1
    return lines


def _uia_obs_lines(read_store: Any, frame: dict[str, Any]) -> list[dict[str, Any]]:
    uia_ref = frame.get("uia_ref") if isinstance(frame.get("uia_ref"), dict) else {}
    uia_record_id = str(uia_ref.get("record_id") or "").strip()
    if not uia_record_id:
        return []
    out: list[dict[str, Any]] = []
    for _record_type, doc_id in _frame_uia_expected_ids(uia_record_id).items():
        row = read_store.get(doc_id, None) if hasattr(read_store, "get") else None
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if text:
            out.append(_line(text))
    return out


def _snapshot_for_frame(read_store: Any, frame: dict[str, Any]) -> dict[str, Any] | None:
    uia_ref = frame.get("uia_ref") if isinstance(frame.get("uia_ref"), dict) else {}
    uia_record_id = str(uia_ref.get("record_id") or "").strip()
    if not uia_record_id:
        return None
    value = read_store.get(uia_record_id, None) if hasattr(read_store, "get") else None
    snapshot = _uia_extract_snapshot_dict(value)
    if not isinstance(snapshot, dict):
        return None
    return snapshot


def _ui_windows(snapshot: dict[str, Any] | None, frame: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(snapshot, dict):
        window = snapshot.get("window") if isinstance(snapshot.get("window"), dict) else {}
        title = str(window.get("title") or "").strip()
        process_path = str(window.get("process_path") or "").strip()
        app = process_path.split("\\")[-1] if process_path else ""
        if title or app:
            out.append(
                {
                    "window_id": "uia_window_1",
                    "label": title,
                    "app": app,
                    "context": "unknown",
                    "visibility": "foreground",
                    "bbox": [0, 0, max(1, _safe_int(frame.get("width"), default=1920)), max(1, _safe_int(frame.get("height"), default=1080))],
                }
            )
    frame_window = frame.get("window") if isinstance(frame.get("window"), dict) else {}
    if isinstance(frame_window, dict) and frame_window:
        title = str(frame_window.get("title") or "").strip()
        app = str(frame_window.get("app") or frame_window.get("process_path") or "").strip()
        if title or app:
            out.append(
                {
                    "window_id": "frame_window_1",
                    "label": title,
                    "app": app,
                    "context": "unknown",
                    "visibility": "foreground",
                    "bbox": [0, 0, max(1, _safe_int(frame.get("width"), default=1920)), max(1, _safe_int(frame.get("height"), default=1080))],
                }
            )
    return out[:8]


def _make_payload(
    *,
    source_record_id: str,
    frame: dict[str, Any],
    snapshot: dict[str, Any] | None,
    read_store: Any,
) -> dict[str, Any]:
    lines: list[dict[str, Any]] = []
    lines.extend(_uia_obs_lines(read_store, frame))
    if isinstance(snapshot, dict):
        lines.extend(_snapshot_lines(snapshot))
    if not lines:
        frame_title = str(frame.get("title") or "").strip()
        if frame_title:
            lines.append(_line(frame_title))

    tokens_raw: list[dict[str, Any]] = []
    for item in lines:
        text = str(item.get("text") or "").strip()
        bbox = _normalized_bbox(item.get("bbox"))
        tok: dict[str, Any] = {"text": text}
        if bbox is not None:
            tok["bbox"] = [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]
        tokens_raw.append(tok)

    width = max(1, _safe_int(frame.get("width") or frame.get("frame_width"), default=1920))
    height = max(1, _safe_int(frame.get("height") or frame.get("frame_height"), default=1080))
    element_graph: dict[str, Any] = {
        "ui_state": {
            "windows": _ui_windows(snapshot, frame),
            "facts": [],
            "image_size": [int(width), int(height)],
        }
    }
    return {
        "source_id": str(source_record_id),
        "record_id": str(source_record_id),
        "text_lines": lines,
        "tokens_raw": tokens_raw,
        "extra_docs": [],
        "element_graph": element_graph,
        "frame_bytes": b"",
    }


def project_stage2_docs_for_frame(
    write_store: Any,
    *,
    source_record_id: str,
    frame_record: dict[str, Any],
    read_store: Any | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Emit deterministic derived.sst.text.extra projection docs for one frame."""
    if not isinstance(frame_record, dict):
        return {"required": False, "ok": True, "generated_docs": 0, "inserted_docs": 0, "errors": 0, "reason": "invalid_record"}
    if str(frame_record.get("record_type") or "") != "evidence.capture.frame":
        return {"required": False, "ok": True, "generated_docs": 0, "inserted_docs": 0, "errors": 0, "reason": "not_frame"}

    reader = read_store if read_store is not None else write_store
    snapshot = _snapshot_for_frame(reader, frame_record)
    payload = _make_payload(
        source_record_id=str(source_record_id),
        frame=frame_record,
        snapshot=snapshot,
        read_store=reader,
    )
    if not isinstance(payload.get("text_lines"), list) or not payload.get("text_lines"):
        return {"required": True, "ok": True, "generated_docs": 0, "inserted_docs": 0, "errors": 0, "reason": "empty_payload"}

    plugin = ObservationGraphPlugin(
        "builtin.observation.graph",
        PluginContext(
            config={},
            get_capability=lambda _name: None,
            logger=lambda _message: None,
        ),
    )
    try:
        result = plugin.run_stage("persist.bundle", payload)
    except Exception as exc:
        return {
            "required": True,
            "ok": False,
            "generated_docs": 0,
            "inserted_docs": 0,
            "errors": 1,
            "reason": f"plugin_error:{type(exc).__name__}",
        }
    docs = result.get("extra_docs") if isinstance(result, dict) and isinstance(result.get("extra_docs"), list) else []
    if not docs:
        return {"required": True, "ok": True, "generated_docs": 0, "inserted_docs": 0, "errors": 0, "reason": "no_docs"}

    normalized_docs: list[tuple[str, str, dict[str, Any]]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        text = str(doc.get("text") or "").strip()
        doc_kind = str(doc.get("doc_kind") or "").strip() or "extra"
        if not text:
            continue
        if doc_kind in {"obs.uia.focus", "obs.uia.context", "obs.uia.operable"}:
            # UIA contract docs are persisted separately as first-class obs.uia.* rows.
            continue
        normalized_docs.append((doc_kind, text, dict(doc)))
    if not normalized_docs:
        return {"required": True, "ok": True, "generated_docs": 0, "inserted_docs": 0, "errors": 0, "reason": "filtered_docs_empty"}

    normalized_docs.sort(key=lambda item: (item[0], item[1]))
    run_id = _run_id_for_frame(str(source_record_id), frame_record)
    ts_utc = _ts_for_frame(frame_record)
    generated = 0
    inserted = 0
    errors = 0
    for index, (doc_kind, text, doc) in enumerate(normalized_docs):
        generated += 1
        component_seed = f"{source_record_id}|{doc_kind}|{index}|{sha256_text(text)[:16]}"
        doc_id = f"{run_id}/derived.sst.text/extra/{encode_record_id_component(component_seed)}"
        existing = write_store.get(doc_id, None) if hasattr(write_store, "get") else None
        if isinstance(existing, dict):
            continue
        bboxes = doc.get("bboxes") if isinstance(doc.get("bboxes"), list) else []
        payload_doc: dict[str, Any] = {
            "schema_version": 1,
            "record_type": "derived.sst.text.extra",
            "run_id": run_id,
            "ts_utc": ts_utc,
            "source_id": str(source_record_id),
            "source_record_id": str(source_record_id),
            "doc_kind": doc_kind,
            "text": text,
            "provider_id": str(doc.get("provider_id") or "builtin.observation.graph"),
            "stage": str(doc.get("stage") or "persist.bundle"),
            "confidence_bp": _safe_int(doc.get("confidence_bp"), default=8000),
            "bboxes": bboxes,
            "meta": doc.get("meta") if isinstance(doc.get("meta"), dict) else {},
            "content_hash": sha256_text(text),
        }
        payload_doc["payload_hash"] = sha256_canonical({k: v for k, v in payload_doc.items() if k != "payload_hash"})
        if dry_run:
            inserted += 1
            continue
        try:
            if hasattr(write_store, "put_new"):
                write_store.put_new(doc_id, payload_doc)
            else:
                write_store.put(doc_id, payload_doc)
            inserted += 1
        except FileExistsError:
            continue
        except Exception:
            errors += 1
            continue

    return {
        "required": True,
        "ok": errors == 0,
        "generated_docs": int(generated),
        "inserted_docs": int(inserted),
        "errors": int(errors),
        "reason": "ok" if errors == 0 else "insert_failed",
    }
