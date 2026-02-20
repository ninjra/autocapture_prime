"""SST stage hook: attach Hypervisor UIA snapshot context as extra docs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.processing.sst.utils import clamp_bbox


_UIA_RECORD_TYPE = "evidence.uia.snapshot"
_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("focus_path", "obs.uia.focus", "focus"),
    ("context_peers", "obs.uia.context", "context"),
    ("operables", "obs.uia.operable", "operable"),
)


@dataclass(frozen=True)
class _UIASettings:
    dataroot: str
    allow_latest_snapshot_fallback: bool
    require_hash_match: bool
    max_focus_nodes: int
    max_context_nodes: int
    max_operable_nodes: int
    drop_offscreen: bool


class UIAContextStageHook(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        self._cfg = _parse_settings(cfg)
        self._metadata = _safe_capability(context, "storage.metadata")

    def capabilities(self) -> dict[str, Any]:
        return {"processing.stage.hooks": self}

    def stages(self) -> list[str]:
        return ["index.text"]

    def run_stage(self, stage: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if stage != "index.text":
            return None
        if not isinstance(payload, dict):
            return None
        record = payload.get("record") if isinstance(payload.get("record"), dict) else {}
        uia_ref = record.get("uia_ref") if isinstance(record.get("uia_ref"), dict) else None
        if not isinstance(uia_ref, dict):
            return None
        try:
            snapshot, source = self._load_snapshot(uia_ref)
            if snapshot is None:
                return None
            docs = _snapshot_to_docs(
                plugin_id=self.plugin_id,
                frame_width=_to_int(payload.get("frame_width"), default=0),
                frame_height=_to_int(payload.get("frame_height"), default=0),
                uia_ref=uia_ref,
                snapshot=snapshot,
                cfg=self._cfg,
            )
            if not docs:
                return None
            return {
                "extra_docs": docs,
                "diagnostics": [
                    {
                        "kind": "uia_context.loaded",
                        "provider_id": str(self.plugin_id),
                        "source": source,
                        "uia_record_id": str(uia_ref.get("record_id") or ""),
                        "count": len(docs),
                    }
                ],
            }
        except Exception as exc:  # pragma: no cover - defensive fail-open
            self._warn("runtime_error", {"error": f"{type(exc).__name__}: {exc}"})
            return None

    def _load_snapshot(self, uia_ref: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        uia_record_id = str(uia_ref.get("record_id") or "").strip()
        if not uia_record_id:
            return None, "none"

        snapshot, metadata_status = self._load_snapshot_from_metadata(uia_ref)
        if snapshot is not None:
            return snapshot, "metadata"
        # Metadata-first contract: only use fallback when the metadata lookup
        # itself fails (missing/unavailable), not when metadata exists but is invalid.
        if metadata_status not in {"lookup_failed"}:
            return None, "none"

        if not self._cfg.allow_latest_snapshot_fallback:
            return None, "none"
        snapshot = self._load_snapshot_from_fallback(uia_ref)
        if snapshot is not None:
            return snapshot, "fallback"
        return None, "none"

    def _load_snapshot_from_metadata(self, uia_ref: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        store = self._metadata
        uia_record_id = str(uia_ref.get("record_id") or "").strip()
        if store is None or not hasattr(store, "get"):
            return None, "lookup_failed"
        try:
            value = store.get(uia_record_id, None)
        except Exception as exc:
            self._warn("metadata_lookup_failed", {"record_id": uia_record_id, "error": type(exc).__name__})
            return None, "lookup_failed"
        if value is None:
            self._warn("metadata_snapshot_missing", {"record_id": uia_record_id})
            return None, "lookup_failed"
        snapshot = _extract_snapshot_dict(value)
        if snapshot is None:
            self._warn("metadata_snapshot_missing", {"record_id": uia_record_id})
            return None, "invalid"
        record_type = str(snapshot.get("record_type") or "").strip()
        if record_type and record_type != _UIA_RECORD_TYPE:
            self._warn(
                "metadata_record_type_mismatch",
                {"record_id": uia_record_id, "record_type": record_type},
            )
            return None, "invalid"
        if not _matches_uia_ref(snapshot, uia_ref, require_hash=self._cfg.require_hash_match):
            self._warn("metadata_hash_mismatch", {"record_id": uia_record_id})
            return None, "invalid"
        return snapshot, "ok"

    def _load_snapshot_from_fallback(self, uia_ref: dict[str, Any]) -> dict[str, Any] | None:
        latest_path = Path(self._cfg.dataroot) / "uia" / "latest.snap.json"
        if not latest_path.exists():
            return None
        try:
            raw_bytes = latest_path.read_bytes()
        except Exception as exc:
            self._warn("fallback_read_failed", {"path": str(latest_path), "error": type(exc).__name__})
            return None
        file_hash = hashlib.sha256(raw_bytes).hexdigest().lower()
        try:
            value = json.loads(raw_bytes.decode("utf-8"))
        except Exception as exc:
            self._warn("fallback_parse_failed", {"path": str(latest_path), "error": type(exc).__name__})
            return None
        snapshot = _extract_snapshot_dict(value)
        if snapshot is None:
            self._warn("fallback_snapshot_missing", {"path": str(latest_path)})
            return None
        snapshot_record_type = str(snapshot.get("record_type") or "").strip()
        if snapshot_record_type and snapshot_record_type != _UIA_RECORD_TYPE:
            self._warn(
                "fallback_record_type_mismatch",
                {"path": str(latest_path), "record_type": snapshot_record_type},
            )
            return None
        if not _fallback_hash_ok(
            snapshot=snapshot,
            uia_ref=uia_ref,
            require_hash=self._cfg.require_hash_match,
            file_hash=file_hash,
            hash_file_path=latest_path.with_suffix(".sha256"),
        ):
            self._warn("fallback_hash_mismatch", {"path": str(latest_path)})
            return None
        return snapshot

    def _warn(self, code: str, payload: dict[str, Any]) -> None:
        message = {"kind": f"uia_context.{code}", **payload}
        try:
            self.context.logger(json.dumps(message, sort_keys=True))
        except Exception:
            return


def create_plugin(plugin_id: str, context: PluginContext) -> UIAContextStageHook:
    return UIAContextStageHook(plugin_id, context)


def _snapshot_to_docs(
    *,
    plugin_id: str,
    frame_width: int,
    frame_height: int,
    uia_ref: dict[str, Any],
    snapshot: dict[str, Any],
    cfg: _UIASettings,
) -> list[dict[str, Any]]:
    uia_record_id = str(uia_ref.get("record_id") or snapshot.get("record_id") or "").strip()
    uia_content_hash = str(uia_ref.get("content_hash") or snapshot.get("content_hash") or "").strip()
    hwnd = str(snapshot.get("hwnd") or "").strip()
    window = snapshot.get("window") if isinstance(snapshot.get("window"), dict) else {}
    window_title = str(window.get("title") or "").strip()
    window_pid = _to_int(window.get("pid"), default=0)
    stats = snapshot.get("stats") if isinstance(snapshot.get("stats"), dict) else {}
    stats_norm = {
        "walk_ms": _to_int(stats.get("walk_ms"), default=0),
        "nodes_emitted": _to_int(stats.get("nodes_emitted"), default=0),
        "failures": _to_int(stats.get("failures"), default=0),
    }

    docs: list[dict[str, Any]] = []
    for section_key, doc_kind, section_label in _SECTIONS:
        raw_nodes = snapshot.get(section_key) if isinstance(snapshot.get(section_key), list) else []
        max_nodes = {
            "focus_path": cfg.max_focus_nodes,
            "context_peers": cfg.max_context_nodes,
            "operables": cfg.max_operable_nodes,
        }[section_key]
        nodes = _normalize_nodes(
            raw_nodes,
            frame_width=frame_width,
            frame_height=frame_height,
            max_nodes=max_nodes,
            drop_offscreen=cfg.drop_offscreen,
        )
        if not nodes:
            continue
        doc_id = _uia_doc_id(uia_record_id, section_label, 0)
        doc_text = json.dumps(
            {
                "kind": doc_kind,
                "window_title": window_title,
                "window_pid": window_pid,
                "hwnd": hwnd,
                "nodes": nodes,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        doc: dict[str, Any] = {
            "doc_id": doc_id,
            "text": doc_text,
            "record_type": doc_kind,
            "doc_kind": doc_kind,
            "meta": {
                "uia_record_id": uia_record_id,
                "uia_content_hash": uia_content_hash,
                "hwnd": hwnd,
                "window_title": window_title,
                "window_pid": window_pid,
                "uia_section": section_label,
                "uia_node_count": len(nodes),
                "uia_nodes": nodes,
                "uia_stats": stats_norm,
            },
            "provider_id": plugin_id,
            "stage": "index.text",
            "confidence_bp": 8500,
            "uia_record_id": uia_record_id,
            "uia_content_hash": uia_content_hash,
            "hwnd": hwnd,
            "window_title": window_title,
            "window_pid": window_pid,
        }
        doc["bboxes"] = [node.get("bbox") for node in nodes if isinstance(node.get("bbox"), list)]
        docs.append(doc)
    return docs


def _normalize_nodes(
    raw_nodes: list[Any],
    *,
    frame_width: int,
    frame_height: int,
    max_nodes: int,
    drop_offscreen: bool,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            continue
        if drop_offscreen and bool(raw.get("offscreen", False)):
            continue
        bbox = _to_bbox(raw.get("rect"), frame_width=frame_width, frame_height=frame_height)
        if bbox is None:
            continue
        node: dict[str, Any] = {
            "eid": str(raw.get("eid") or "").strip(),
            "role": str(raw.get("role") or "").strip(),
            "name": str(raw.get("name") or "").strip(),
            "aid": str(raw.get("aid") or "").strip(),
            "class": str(raw.get("class") or "").strip(),
            "bbox": list(bbox),
            "bbox_norm_bp": list(_bbox_norm_bp(bbox, frame_width=frame_width, frame_height=frame_height)),
            "enabled": bool(raw.get("enabled", False)),
            "offscreen": bool(raw.get("offscreen", False)),
        }
        if "hot" in raw:
            node["hot"] = bool(raw.get("hot"))
        out.append(node)
        if len(out) >= max(1, int(max_nodes)):
            break
    return out


def _to_bbox(value: Any, *, frame_width: int, frame_height: int) -> tuple[int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        left = int(round(float(value[0])))
        t = int(round(float(value[1])))
        r = int(round(float(value[2])))
        b = int(round(float(value[3])))
    except Exception:
        return None
    width = max(1, int(frame_width))
    height = max(1, int(frame_height))
    return clamp_bbox((left, t, r, b), width=width, height=height)


def _bbox_norm_bp(
    bbox: tuple[int, int, int, int],
    *,
    frame_width: int,
    frame_height: int,
) -> tuple[int, int, int, int]:
    left, t, r, b = bbox
    width = max(1, int(frame_width))
    height = max(1, int(frame_height))
    return (
        _clamp_bp((left * 10000) // width),
        _clamp_bp((t * 10000) // height),
        _clamp_bp((r * 10000) // width),
        _clamp_bp((b * 10000) // height),
    )


def _clamp_bp(value: int) -> int:
    if value < 0:
        return 0
    if value > 10000:
        return 10000
    return int(value)


def _uia_doc_id(uia_record_id: str, section: str, index: int) -> str:
    seed = f"uia-{uia_record_id}-{section}-{int(index)}"
    component = encode_record_id_component(seed)
    run_id = str(uia_record_id).split("/", 1)[0] if "/" in str(uia_record_id) else "run"
    return f"{run_id}/derived.sst.text/extra/{component}"


def _extract_snapshot_dict(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    candidate = value.get("payload") if isinstance(value.get("payload"), dict) else value
    if not isinstance(candidate, dict):
        return None
    out = dict(candidate)
    record_type = str(out.get("record_type") or value.get("record_type") or "").strip()
    if record_type:
        out["record_type"] = record_type
    if "record_id" not in out and "record_id" in value:
        out["record_id"] = value.get("record_id")
    if "content_hash" not in out and "content_hash" in value:
        out["content_hash"] = value.get("content_hash")
    return out


def _matches_uia_ref(snapshot: dict[str, Any], uia_ref: dict[str, Any], *, require_hash: bool) -> bool:
    ref_record_id = str(uia_ref.get("record_id") or "").strip()
    snap_record_id = str(snapshot.get("record_id") or "").strip()
    if ref_record_id and snap_record_id and ref_record_id != snap_record_id:
        return False
    if not require_hash:
        return True
    ref_hash = str(uia_ref.get("content_hash") or "").strip().lower()
    snap_hash = str(snapshot.get("content_hash") or "").strip().lower()
    if ref_hash and snap_hash and ref_hash != snap_hash:
        return False
    return True


def _fallback_hash_ok(
    *,
    snapshot: dict[str, Any],
    uia_ref: dict[str, Any],
    require_hash: bool,
    file_hash: str,
    hash_file_path: Path,
) -> bool:
    if not _matches_uia_ref(snapshot, uia_ref, require_hash=False):
        return False
    ref_hash = str(uia_ref.get("content_hash") or "").strip().lower()
    snap_hash = str(snapshot.get("content_hash") or "").strip().lower()
    hash_file_value = _read_hash_file(hash_file_path)

    # Fallback integrity gate: strict mode requires valid sidecar hash file
    # and exact match with latest.snap.json content hash.
    if not hash_file_value:
        return False
    if hash_file_value and hash_file_value != file_hash:
        return False
    if not require_hash:
        if ref_hash and snap_hash and ref_hash != snap_hash:
            return False
        return True
    if ref_hash and snap_hash:
        if ref_hash != snap_hash:
            return False
        return True
    if ref_hash and not snap_hash:
        return file_hash == ref_hash
    if snap_hash:
        return True
    if hash_file_value:
        return True
    return False


def _read_hash_file(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not raw:
        return None
    token = raw.split()[0].strip().lower()
    if len(token) != 64:
        return None
    for ch in token:
        if ch not in "0123456789abcdef":
            return None
    return token


def _to_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_capability(context: PluginContext, name: str) -> Any | None:
    try:
        return context.get_capability(name)
    except Exception:
        return None


def _parse_settings(cfg: dict[str, Any]) -> _UIASettings:
    return _UIASettings(
        dataroot=str(cfg.get("dataroot") or "/mnt/d/autocapture"),
        allow_latest_snapshot_fallback=bool(cfg.get("allow_latest_snapshot_fallback", True)),
        require_hash_match=bool(cfg.get("require_hash_match", True)),
        max_focus_nodes=max(1, _to_int(cfg.get("max_focus_nodes"), default=64)),
        max_context_nodes=max(1, _to_int(cfg.get("max_context_nodes"), default=96)),
        max_operable_nodes=max(1, _to_int(cfg.get("max_operable_nodes"), default=128)),
        drop_offscreen=bool(cfg.get("drop_offscreen", True)),
    )
