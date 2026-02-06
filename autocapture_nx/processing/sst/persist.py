"""Persistence and indexing for SST artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.kernel.hashing import sha256_canonical, sha256_text

from .utils import hash_canonical


IndexTextFn = Callable[[str, str], None]


@dataclass(frozen=True)
class PersistStats:
    derived_records: int
    indexed_docs: int
    derived_ids: tuple[str, ...]
    indexed_ids: tuple[str, ...]


class SSTPersistence:
    def __init__(
        self,
        *,
        metadata: Any,
        event_builder: Any | None,
        index_text: IndexTextFn,
        extractor_id: str,
        extractor_version: str,
        config_hash: str,
        schema_version: int,
    ) -> None:
        self._metadata = metadata
        self._event_builder = event_builder
        self._index_text = index_text
        self._extractor = {
            "id": extractor_id,
            "version": extractor_version,
            "config_hash": config_hash,
        }
        self._schema_version = int(schema_version)
        self._last_error: str | None = None

    def _debug_log(self, entry: dict[str, Any]) -> None:
        data_dir = os.environ.get("AUTOCAPTURE_DATA_DIR")
        if not data_dir:
            return
        try:
            log_path = Path(data_dir) / "logs" / "sst_persist_debug.jsonl"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
        except Exception:
            return

    def persist_frame(
        self,
        *,
        run_id: str,
        record_id: str,
        ts_ms: int,
        width: int,
        height: int,
        image_sha256: str,
        phash: str,
        boundary: bool,
        boundary_reason: str,
        phash_distance: int,
        diff_score_bp: int,
    ) -> PersistStats:
        encoded_source = encode_record_id_component(record_id)
        derived_id = f"{run_id}/derived.sst.frame/{encoded_source}"
        payload = self._envelope(
            artifact_id=derived_id,
            kind="FrameTrace",
            ts_ms=ts_ms,
            record_id=record_id,
            state_ids=(),
            bboxes=((0, 0, width, height),),
            image_sha256=image_sha256,
            confidence_bp=10000,
            payload={
                "record_type": "derived.sst.frame",
                "frame_id": record_id,
                "width": int(width),
                "height": int(height),
                "phash": phash,
                "state_boundary": bool(boundary),
                "boundary_reason": str(boundary_reason),
                "phash_distance": int(phash_distance),
                "diff_score_bp": int(diff_score_bp),
            },
        )
        created = self._put_new(derived_id, payload)
        if created:
            self._emit_event("sst.frame", payload, inputs=(record_id,), outputs=(derived_id,))
        derived_ids = (derived_id,) if created else ()
        return PersistStats(derived_records=1 if created else 0, indexed_docs=0, derived_ids=derived_ids, indexed_ids=())

    def persist_state_bundle(
        self,
        *,
        run_id: str,
        record_id: str,
        state: dict[str, Any],
        image_sha256: str,
        frame_bbox: tuple[int, int, int, int],
        prev_record_id: str | None,
        delta_event: dict[str, Any] | None,
        action_event: dict[str, Any] | None,
        extra_docs: list[dict[str, Any]] | None = None,
    ) -> PersistStats:
        derived_records = 0
        indexed_docs = 0
        derived_ids: list[str] = []
        indexed_ids: list[str] = []

        state_id = state["state_id"]
        screen_state, normalized = _ensure_json(state)
        state_record_id = f"{run_id}/derived.sst.state/{_state_record_component(record_id)}"
        state_payload = self._envelope(
            artifact_id=state_record_id,
            kind="ScreenState",
            ts_ms=int(state["ts_ms"]),
            record_id=record_id,
            state_ids=(state_id,),
            bboxes=(frame_bbox,),
            image_sha256=image_sha256,
            confidence_bp=int(state.get("state_confidence_bp", 0)),
            payload={
                "record_type": "derived.sst.state",
                "state_id": state_id,
                "frame_id": state.get("frame_id"),
                "phash": state.get("phash"),
                "screen_state": screen_state,
                "screen_state_normalized": bool(normalized),
                "summary": {
                    "visible_apps": tuple(state.get("visible_apps", ())),
                    "focus_element_id": state.get("focus_element_id"),
                    "token_count": len(state.get("tokens", ())),
                    "table_count": len(state.get("tables", ())),
                    "spreadsheet_count": len(state.get("spreadsheets", ())),
                    "code_count": len(state.get("code_blocks", ())),
                    "chart_count": len(state.get("charts", ())),
                },
            },
        )
        payload_normalized = False
        try:
            json.dumps(state_payload, sort_keys=True)
        except Exception as exc:
            extra_docs = list(extra_docs or [])
            extra_docs.append(
                {
                    "text": f"state_payload_json_error:{type(exc).__name__}:{exc}",
                    "doc_kind": "state.persist.error",
                    "provider_id": "sst.persist",
                    "stage": "persist.bundle",
                    "confidence_bp": 1000,
                }
            )
        state_payload, payload_normalized = _ensure_json(state_payload)
        if payload_normalized and isinstance(state_payload, dict):
            state_payload["payload_normalized"] = True
            self._debug_log(
                {
                    "event": "sst.state.payload_normalized",
                    "record_id": record_id,
                    "state_record_id": state_record_id,
                    "state_id": state_id,
                }
            )
        state_created = self._put_new(state_record_id, state_payload)
        if state_created:
            derived_records += 1
            derived_ids.append(state_record_id)
            self._emit_event("sst.state", state_payload, inputs=(record_id,), outputs=(state_record_id,))
        elif self._last_error:
            extra_docs = list(extra_docs or [])
            extra_docs.append(
                {
                    "text": f"state_persist_error:{self._last_error}",
                    "doc_kind": "state.persist.error",
                    "provider_id": "sst.persist",
                    "stage": "persist.bundle",
                    "confidence_bp": 1000,
                }
            )
            self._debug_log(
                {
                    "event": "sst.state.persist_failed",
                    "record_id": record_id,
                    "state_record_id": state_record_id,
                    "state_id": state_id,
                    "error": self._last_error,
                }
            )

        docs = list(_state_docs(run_id, state))
        doc_records: list[tuple[str, dict[str, Any]]] = []
        for doc_id, doc_text, meta in docs:
            doc_payload = self._envelope(
                artifact_id=doc_id,
                kind="TextDoc",
                ts_ms=int(state["ts_ms"]),
                record_id=record_id,
                state_ids=(state_id,),
                bboxes=(frame_bbox,),
                image_sha256=image_sha256,
                confidence_bp=int(state.get("state_confidence_bp", 0)),
                payload={
                    "record_type": "derived.sst.text",
                    "state_id": state_id,
                    "text": doc_text,
                    **meta,
                },
            )
            doc_records.append((doc_id, doc_payload))
        inserted_docs = self._put_batch(doc_records)
        for doc_id, doc_text, _meta in docs:
            if doc_id in inserted_docs:
                derived_records += 1
                derived_ids.append(doc_id)
            self._index_text(doc_id, doc_text)
            indexed_docs += 1
            indexed_ids.append(doc_id)

        extra_records: list[tuple[str, dict[str, Any]]] = []
        extra_meta: list[tuple[str, str, dict[str, Any]]] = []
        for doc in extra_docs or ():
            if not isinstance(doc, dict):
                continue
            text = str(doc.get("text", "")).strip()
            if not text:
                continue
            doc_id = str(doc.get("doc_id", "")).strip()
            if not doc_id:
                digest = sha256_text(text)[:16]
                doc_component = encode_record_id_component(f"extra-{state_id}-{digest}")
                doc_id = f"{run_id}/derived.sst.text/extra/{doc_component}"
            doc_kind = str(doc.get("doc_kind", "extra") or "extra").strip() or "extra"
            meta = doc.get("meta", {})
            if not isinstance(meta, dict):
                meta = {}
            provider_id = str(doc.get("provider_id", "")).strip()
            stage = str(doc.get("stage", "")).strip()
            confidence_bp = _bp_int(doc.get("confidence_bp", 8000))
            bboxes = _extra_doc_bboxes(doc, default_bbox=frame_bbox)
            payload: dict[str, Any] = {
                "record_type": "derived.sst.text.extra",
                "state_id": state_id,
                "doc_kind": doc_kind,
                "text": text,
                **meta,
            }
            if provider_id:
                payload["provider_id"] = provider_id
            if stage:
                payload["stage"] = stage
            doc_payload = self._envelope(
                artifact_id=doc_id,
                kind="TextDoc",
                ts_ms=int(state["ts_ms"]),
                record_id=record_id,
                state_ids=(state_id,),
                bboxes=bboxes,
                image_sha256=image_sha256,
                confidence_bp=confidence_bp,
                payload=payload,
            )
            extra_records.append((doc_id, doc_payload))
            extra_meta.append((doc_id, text, doc_payload))
        inserted_extra = self._put_batch(extra_records)
        for doc_id, text, doc_payload in extra_meta:
            if doc_id in inserted_extra:
                derived_records += 1
                derived_ids.append(doc_id)
                self._emit_event("sst.extra_doc", doc_payload, inputs=(record_id,), outputs=(doc_id,))
            self._index_text(doc_id, text)
            indexed_docs += 1
            indexed_ids.append(doc_id)

        if delta_event:
            delta_id = delta_event["delta_id"]
            delta_record_id = f"{run_id}/derived.sst.delta/{encode_record_id_component(delta_id)}"
            delta_payload = self._envelope(
                artifact_id=delta_record_id,
                kind="DeltaEvent",
                ts_ms=int(delta_event["ts_ms"]),
                record_id=record_id,
                state_ids=(delta_event["from_state_id"], delta_event["to_state_id"]),
                bboxes=(frame_bbox,),
                image_sha256=image_sha256,
                confidence_bp=9000,
                payload={
                    "record_type": "derived.sst.delta",
                    "delta_id": delta_id,
                    "from_state_id": delta_event["from_state_id"],
                    "to_state_id": delta_event["to_state_id"],
                    "delta_event": delta_event,
                    "summary": delta_event["summary"],
                    "change_count": len(delta_event.get("changes", ())),
                },
            )
            if self._put_new(delta_record_id, delta_payload):
                derived_records += 1
                derived_ids.append(delta_record_id)
                self._emit_event(
                    "sst.delta",
                    delta_payload,
                    inputs=tuple(x for x in (prev_record_id, record_id) if x),
                    outputs=(delta_record_id,),
                )

        if action_event:
            action_id = action_event["action_id"]
            action_record_id = f"{run_id}/derived.sst.action/{encode_record_id_component(action_id)}"
            action_payload = self._envelope(
                artifact_id=action_record_id,
                kind="ActionEvent",
                ts_ms=int(action_event["ts_ms"]),
                record_id=record_id,
                state_ids=(action_event["from_state_id"], action_event["to_state_id"]),
                bboxes=(frame_bbox,),
                image_sha256=image_sha256,
                confidence_bp=int(action_event["primary"]["confidence_bp"]),
                payload={
                    "record_type": "derived.sst.action",
                    "action_id": action_id,
                    "from_state_id": action_event["from_state_id"],
                    "to_state_id": action_event["to_state_id"],
                    "primary": action_event["primary"],
                    "alternatives": action_event["alternatives"],
                    "impact": action_event["impact"],
                },
            )
            if self._put_new(action_record_id, action_payload):
                derived_records += 1
                derived_ids.append(action_record_id)
                self._emit_event("sst.action", action_payload, inputs=(record_id,), outputs=(action_record_id,))

        return PersistStats(
            derived_records=derived_records,
            indexed_docs=indexed_docs,
            derived_ids=tuple(derived_ids),
            indexed_ids=tuple(indexed_ids),
        )

    def _envelope(
        self,
        *,
        artifact_id: str,
        kind: str,
        ts_ms: int,
        record_id: str,
        state_ids: Iterable[str],
        bboxes: Iterable[tuple[int, int, int, int]],
        image_sha256: str,
        confidence_bp: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        run_id = artifact_id.split("/", 1)[0] if "/" in artifact_id else "run"
        ts_utc = datetime.fromtimestamp(int(ts_ms) / 1000.0, tz=timezone.utc).isoformat()
        envelope = {
            **payload,
            "run_id": run_id,
            "artifact_id": artifact_id,
            "kind": kind,
            "schema_version": self._schema_version,
            "created_ts_ms": int(ts_ms),
            "ts_utc": payload.get("ts_utc") or ts_utc,
            "extractor": self._extractor,
            "provenance": {
                "frame_ids": (record_id,),
                "state_ids": tuple(state_ids),
                "bboxes": tuple(tuple(int(v) for v in bbox) for bbox in bboxes),
                "input_image_sha256": (image_sha256,),
            },
            "confidence_bp": int(confidence_bp),
        }
        if "source_id" not in envelope:
            envelope["source_id"] = record_id
        if "content_hash" not in envelope:
            envelope["content_hash"] = sha256_canonical(envelope)
        envelope["payload_hash"] = sha256_canonical({k: v for k, v in envelope.items() if k != "payload_hash"})
        return envelope

    def _put_new(self, record_id: str, payload: dict[str, Any]) -> bool:
        self._last_error = None
        existing = self._metadata.get(record_id, None)
        if existing is not None:
            self._last_error = "exists"
            return False
        if hasattr(self._metadata, "put_new"):
            try:
                self._metadata.put_new(record_id, payload)
                return True
            except Exception as exc:
                self._last_error = f"put_new_failed:{type(exc).__name__}:{exc}"
                return False
        try:
            self._metadata.put(record_id, payload)
            return True
        except Exception as exc:
            self._last_error = f"put_failed:{type(exc).__name__}:{exc}"
            return False

    def _put_batch(self, records: list[tuple[str, dict[str, Any]]]) -> set[str]:
        if not records:
            return set()
        if hasattr(self._metadata, "put_batch"):
            try:
                batch_result = self._metadata.put_batch(records)
                if batch_result is None:
                    return {record_id for record_id, _ in records}
                return {str(record_id) for record_id in batch_result}
            except Exception:
                return set()
        inserted: set[str] = set()
        for record_id, payload in records:
            if self._put_new(record_id, payload):
                inserted.add(record_id)
        return inserted

    def _emit_event(self, event_type: str, payload: dict[str, Any], *, inputs: tuple[str, ...], outputs: tuple[str, ...]) -> None:
        if not self._event_builder:
            return
        try:
            self._event_builder.journal_event(event_type, payload, event_id=payload["artifact_id"], ts_utc=None)
            self._event_builder.ledger_entry(
                event_type,
                inputs=list(inputs),
                outputs=list(outputs),
                payload=payload,
                entry_id=payload["artifact_id"],
                ts_utc=None,
            )
        except Exception:
            return


def _state_docs(run_id: str, state: dict[str, Any]) -> Iterable[tuple[str, str, dict[str, Any]]]:
    state_id = state["state_id"]
    state_component = encode_record_id_component(state_id)

    full_text_parts = []
    for block in state.get("text_blocks", ()):
        text = str(block.get("text", "")).strip()
        if text:
            full_text_parts.append(text)
    for table in state.get("tables", ()):
        csv_text = str(table.get("csv", "")).strip()
        if csv_text:
            full_text_parts.append(csv_text)
    for code in state.get("code_blocks", ()):
        text = str(code.get("text", "")).strip()
        if text:
            full_text_parts.append(text)
    full_text = "\n".join(full_text_parts).strip()
    if full_text:
        doc_id = f"{run_id}/derived.sst.text/state/{state_component}"
        yield doc_id, full_text, {"doc_kind": "state"}

    for table in state.get("tables", ()):
        table_id = str(table.get("table_id"))
        cells = table.get("cells", ())
        cell_lines = []
        for cell in cells:
            cell_lines.append(f"R{cell['r']}C{cell['c']}: {cell.get('text', '')}")
        text = "\n".join(cell_lines).strip()
        if not text:
            continue
        table_component = encode_record_id_component(table_id)
        doc_id = f"{run_id}/derived.sst.text/table/{table_component}"
        yield doc_id, text, {"doc_kind": "table", "table_id": table_id}

    for code in state.get("code_blocks", ()):
        code_id = str(code.get("code_id"))
        text = str(code.get("text", "")).strip()
        if not text:
            continue
        code_component = encode_record_id_component(code_id)
        doc_id = f"{run_id}/derived.sst.text/code/{code_component}"
        yield doc_id, text, {"doc_kind": "code", "code_id": code_id, "language": code.get("language")}


def _bp_int(value: Any) -> int:
    try:
        bp = int(value)
    except Exception:
        bp = 0
    if bp < 0:
        return 0
    if bp > 10000:
        return 10000
    return bp


def _state_record_component(record_id: str) -> str:
    return f"rid_{sha256_text(record_id)}"


def _normalize_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"__bytes_len": len(value), "__bytes_sha256": sha256_text(value.hex())}
    if isinstance(value, dict):
        return {str(key): _normalize_json(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_json(item) for item in value]
    return str(value)


def _ensure_json(value: Any) -> tuple[Any, bool]:
    try:
        json.dumps(value, sort_keys=True)
        return value, False
    except TypeError:
        return _normalize_json(value), True


def _extra_doc_bboxes(doc: dict[str, Any], *, default_bbox: tuple[int, int, int, int]) -> tuple[tuple[int, int, int, int], ...]:
    def _coerce_bbox(value: Any) -> tuple[int, int, int, int] | None:
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            return None
        try:
            x1, y1, x2, y2 = (int(value[0]), int(value[1]), int(value[2]), int(value[3]))
        except Exception:
            return None
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        return (x1, y1, x2, y2)

    boxes: list[tuple[int, int, int, int]] = []
    raw = doc.get("bboxes")
    if isinstance(raw, (list, tuple)) and raw:
        first = raw[0]
        if isinstance(first, (list, tuple)) and len(first) == 4:
            for item in raw:
                bbox = _coerce_bbox(item)
                if bbox is not None:
                    boxes.append(bbox)
        else:
            bbox = _coerce_bbox(raw)
            if bbox is not None:
                boxes.append(bbox)
    if not boxes:
        bbox = _coerce_bbox(doc.get("bbox"))
        if bbox is not None:
            boxes.append(bbox)
    if not boxes:
        boxes.append(
            (
                int(default_bbox[0]),
                int(default_bbox[1]),
                int(default_bbox[2]),
                int(default_bbox[3]),
            )
        )
    return tuple(boxes)


def config_hash(config: dict[str, Any]) -> str:
    """Return a stable hash for SST config blocks."""
    try:
        return hash_canonical(config)
    except Exception:
        return sha256_text(str(sorted(config.items())))
