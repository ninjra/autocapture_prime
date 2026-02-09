"""Filesystem media store plugin (content-addressed).

This is intended as a lightweight alternative to database-backed blob storage:
- Media blobs are stored as files under `storage.media_dir`.
- Record IDs are typically `media/sha256/<sha256hex>`.
- Writes are atomic (temp + rename). No deletion is performed.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from autocapture_nx.kernel.atomic_write import atomic_write_bytes
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


def _safe_rel(path: str) -> str:
    text = str(path or "").strip().replace("\\", "/")
    while text.startswith("/"):
        text = text[1:]
    if ".." in text.split("/"):
        raise ValueError("invalid_record_id_path")
    return text


@dataclass(frozen=True)
class MediaPath:
    root: Path
    rel: str

    @property
    def abs(self) -> Path:
        return self.root / self.rel


class FilesystemMediaStore:
    def __init__(self, root: str, *, fsync_policy: str | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._fsync_policy = str(fsync_policy or "").strip().lower() or None

    def _path_for(self, record_id: str) -> MediaPath:
        rel = _safe_rel(record_id)
        # Place by prefix shard to keep directories small.
        parts = rel.split("/")
        if len(parts) >= 3 and parts[0] == "media" and parts[1] == "sha256" and len(parts[2]) >= 2:
            shard = parts[2][:2]
            rel = "/".join([parts[0], parts[1], shard] + parts[2:])
        rel = rel + ".blob"
        return MediaPath(root=self.root, rel=rel)

    def exists(self, record_id: str) -> bool:
        try:
            return self._path_for(record_id).abs.exists()
        except Exception:
            return False

    def get(self, record_id: str, default: bytes | None = None) -> bytes | None:
        try:
            path = self._path_for(record_id).abs
            if not path.exists():
                return default
            return path.read_bytes()
        except Exception:
            return default

    def open_stream(self, record_id: str):
        path = self._path_for(record_id).abs
        return path.open("rb")

    def put_new(self, record_id: str, data: bytes, *, ts_utc: str | None = None, fsync_policy: str | None = None) -> None:
        _ = ts_utc
        path = self._path_for(record_id).abs
        if path.exists():
            raise FileExistsError(record_id)
        atomic_write_bytes(path, data, fsync_policy=fsync_policy or self._fsync_policy)

    def put_stream(self, record_id: str, stream: BinaryIO, chunk_size: int = 1024 * 1024, *, ts_utc: str | None = None) -> None:
        _ = ts_utc
        path = self._path_for(record_id).abs
        if path.exists():
            raise FileExistsError(record_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Stream to temp file then rename.
        with tempfile.NamedTemporaryFile(prefix=path.name + ".", dir=str(path.parent), delete=False) as tmp:
            tmp_path = Path(tmp.name)
            try:
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        break
                    tmp.write(chunk)
                tmp.flush()
                os.fsync(tmp.fileno())
            finally:
                try:
                    tmp.close()
                except Exception:
                    pass
        os.replace(str(tmp_path), str(path))
        # Directory fsync is best-effort; atomic_write_bytes already does this for some policies.
        if (self._fsync_policy or "").lower() in {"critical", "always"}:
            try:
                fd = os.open(str(path.parent), os.O_DIRECTORY)
            except Exception:
                fd = None
            if fd is not None:
                try:
                    os.fsync(fd)
                except Exception:
                    pass
                finally:
                    try:
                        os.close(fd)
                    except Exception:
                        pass

    def count(self) -> int:
        total = 0
        try:
            for _ in self.root.rglob("*.blob"):
                total += 1
        except Exception:
            return total
        return total


class StorageMediaBasicPlugin(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        storage = context.config.get("storage", {}) if isinstance(context.config, dict) else {}
        media_dir = str(storage.get("media_dir", "data/media") or "data/media")
        fsync_policy = storage.get("fsync_policy")
        self._media = FilesystemMediaStore(media_dir, fsync_policy=fsync_policy)

    def capabilities(self) -> dict[str, Any]:
        return {"storage.media": self._media}


def create_plugin(plugin_id: str, context: PluginContext) -> StorageMediaBasicPlugin:
    return StorageMediaBasicPlugin(plugin_id, context)

