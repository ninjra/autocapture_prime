from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .proto_decode import parse_batch_bytes


ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def _maybe_decompress_zstd(blob: bytes) -> bytes:
    if blob.startswith(ZSTD_MAGIC):
        try:
            import zstandard as zstd  # type: ignore
        except Exception as exc:
            raise RuntimeError("zstandard module required to decode .pb.zst payload") from exc
        return zstd.ZstdDecompressor().decompress(blob)
    try:
        import zstandard as zstd  # type: ignore
    except Exception:
        return blob
    try:
        return zstd.ZstdDecompressor().decompress(blob)
    except Exception:
        return blob


def _load_batch_blob(path: Path, kind: str) -> Any:
    raw = path.read_bytes()
    data = _maybe_decompress_zstd(raw)
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        try:
            return {"items": parse_batch_bytes(kind, data)}
        except Exception:
            return {}


@dataclass(frozen=True)
class LoadedSession:
    session_dir: Path
    manifest: dict[str, Any]
    frames_meta: list[dict[str, Any]]
    input_events: list[dict[str, Any]]
    detections: list[dict[str, Any]]


class SessionLoader:
    """Load a complete chronicle session from spool layout."""

    def __init__(self, session_dir: Path) -> None:
        self.session_dir = Path(session_dir)

    def load(self) -> LoadedSession:
        manifest_path = self.session_dir / "manifest.json"
        meta_dir = self.session_dir / "meta"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        frames_meta_blob = _load_batch_blob(meta_dir / "frames.pb.zst", "frames") if (meta_dir / "frames.pb.zst").exists() else {}
        input_blob = _load_batch_blob(meta_dir / "input.pb.zst", "input") if (meta_dir / "input.pb.zst").exists() else {}
        detections_blob = _load_batch_blob(meta_dir / "detections.pb.zst", "detections") if (meta_dir / "detections.pb.zst").exists() else {}

        frames_meta = _to_items(frames_meta_blob)
        input_events = _to_items(input_blob)
        detections = _to_items(detections_blob)
        return LoadedSession(
            session_dir=self.session_dir,
            manifest=manifest if isinstance(manifest, dict) else {},
            frames_meta=frames_meta,
            input_events=input_events,
            detections=detections,
        )

    def iter_frames(self, loaded: LoadedSession) -> Iterator[tuple[Path, dict[str, Any]]]:
        for item in loaded.frames_meta:
            path_rel = str(item.get("artifact_path") or "")
            if not path_rel:
                frame_index = int(item.get("frame_index", 0))
                candidate = self.session_dir / "frames" / f"frame_{frame_index:06d}.png"
            else:
                candidate = self.session_dir / path_rel
            if candidate.exists():
                yield candidate, item


def _to_items(blob: Any) -> list[dict[str, Any]]:
    if isinstance(blob, dict) and isinstance(blob.get("items"), list):
        return [item for item in blob["items"] if isinstance(item, dict)]
    if isinstance(blob, list):
        return [item for item in blob if isinstance(item, dict)]
    return []
