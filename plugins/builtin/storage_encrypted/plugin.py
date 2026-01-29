"""Encrypted storage plugin using AES-GCM."""

from __future__ import annotations

import base64
import json
import os
import struct
from datetime import datetime, timezone
from typing import Any, Iterable

from autocapture_nx.kernel.crypto import (
    EncryptedBlob,
    EncryptedBlobRaw,
    decrypt_bytes,
    decrypt_bytes_raw,
    derive_key,
    encrypt_bytes,
    encrypt_bytes_raw,
)
from autocapture_nx.kernel.metadata_store import ImmutableMetadataStore
from autocapture_nx.kernel.keyring import KeyRing
from autocapture_nx.plugin_system.api import PluginBase, PluginContext

ENC_PREFIX = "rid_"
BLOB_MAGIC = b"ACNXBLOB1"
STREAM_MAGIC = b"ACNXSTR1"
BLOB_EXT = ".blob"
STREAM_EXT = ".stream"


class _FsyncPolicy:
    NONE = "none"
    BULK = "bulk"
    CRITICAL = "critical"

    @classmethod
    def normalize(cls, value: str | None) -> str:
        if not value:
            return cls.NONE
        value = str(value).strip().lower()
        if value in (cls.NONE, cls.BULK, cls.CRITICAL):
            return value
        return cls.NONE


def _fsync_file(handle, policy: str) -> None:
    if policy == _FsyncPolicy.NONE:
        return
    try:
        handle.flush()
        os.fsync(handle.fileno())
    except OSError:
        return


def _fsync_dir(path: str, policy: str) -> None:
    if policy != _FsyncPolicy.CRITICAL:
        return
    parent = os.path.dirname(path) or "."
    try:
        fd = os.open(parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _atomic_write_json(path: str, payload: dict, *, fsync_policy: str) -> None:
    tmp_path = f"{path}.tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
        _fsync_file(handle, fsync_policy)
    os.replace(tmp_path, path)
    _fsync_dir(path, fsync_policy)


def _atomic_write_bytes(path: str, payload: bytes, *, fsync_policy: str) -> None:
    tmp_path = f"{path}.tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp_path, "wb") as handle:
        handle.write(payload)
        _fsync_file(handle, fsync_policy)
    os.replace(tmp_path, path)
    _fsync_dir(path, fsync_policy)


def _encode_record_id(record_id: str) -> str:
    token = base64.urlsafe_b64encode(record_id.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{ENC_PREFIX}{token}"


def _decode_record_id(token: str) -> str:
    if not token.startswith(ENC_PREFIX):
        return token
    raw = token[len(ENC_PREFIX) :]
    padded = raw + "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception:
        return token


def _legacy_safe_id(record_id: str) -> str:
    return record_id.replace("/", "_")


def _parse_ts(ts_utc: str | None) -> datetime:
    if not ts_utc:
        return datetime.now(timezone.utc)
    if ts_utc.endswith("Z"):
        ts_utc = ts_utc[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts_utc)
    except Exception:
        return datetime.now(timezone.utc)


def _extract_ts(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("ts_utc", "ts_start_utc", "ts_end_utc"):
            if value.get(key):
                return str(value.get(key))
    return None


def _classify_record_kind(record_id: str | None, record_type: str | None = None) -> str:
    if record_type and str(record_type).startswith("derived."):
        return "derived"
    token = (record_id or "").lower()
    if "/derived." in token or token.startswith("derived.") or "/derived/" in token:
        return "derived"
    return "evidence"


def _shard_dir(
    root_dir: str,
    run_id: str,
    ts_utc: str | None,
    *,
    record_id: str | None = None,
    record_type: str | None = None,
) -> str:
    dt = _parse_ts(ts_utc)
    safe_run = _encode_record_id(run_id or "run")
    kind = _classify_record_kind(record_id, record_type)
    return os.path.join(
        root_dir,
        safe_run,
        kind,
        f"{dt.year:04d}",
        f"{dt.month:02d}",
        f"{dt.day:02d}",
    )


def _iter_files(root_dir: str, extensions: Iterable[str]) -> Iterable[str]:
    ext_set = set(extensions)
    for current, _dirs, files in os.walk(root_dir):
        for filename in files:
            for ext in ext_set:
                if filename.endswith(ext):
                    yield os.path.join(current, filename)
                    break


def _read_exact(handle, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise ValueError("Truncated encrypted blob")
    return data


def _pack_blob(blob: EncryptedBlobRaw) -> bytes:
    key_id_bytes = blob.key_id.encode("utf-8") if blob.key_id else b""
    parts = [
        BLOB_MAGIC,
        struct.pack(">H", len(key_id_bytes)),
        key_id_bytes,
        struct.pack(">H", len(blob.nonce)),
        blob.nonce,
        struct.pack(">Q", len(blob.ciphertext)),
        blob.ciphertext,
    ]
    return b"".join(parts)


def _unpack_blob(handle) -> EncryptedBlobRaw:
    magic = _read_exact(handle, len(BLOB_MAGIC))
    if magic != BLOB_MAGIC:
        raise ValueError("Unknown blob format")
    key_len = struct.unpack(">H", _read_exact(handle, 2))[0]
    key_id = _read_exact(handle, key_len).decode("utf-8") if key_len else None
    nonce_len = struct.unpack(">H", _read_exact(handle, 2))[0]
    nonce = _read_exact(handle, nonce_len)
    cipher_len = struct.unpack(">Q", _read_exact(handle, 8))[0]
    ciphertext = _read_exact(handle, cipher_len)
    return EncryptedBlobRaw(nonce=nonce, ciphertext=ciphertext, key_id=key_id)


def _read_stream_header(handle) -> tuple[str | None, int]:
    magic = _read_exact(handle, len(STREAM_MAGIC))
    if magic != STREAM_MAGIC:
        raise ValueError("Unknown stream format")
    key_len = struct.unpack(">H", _read_exact(handle, 2))[0]
    key_id = _read_exact(handle, key_len).decode("utf-8") if key_len else None
    return key_id, handle.tell()


def _iter_stream_chunks(handle) -> Iterable[EncryptedBlobRaw]:
    while True:
        prefix = handle.read(2)
        if not prefix:
            break
        if len(prefix) != 2:
            raise ValueError("Truncated stream chunk header")
        nonce_len = struct.unpack(">H", prefix)[0]
        nonce = _read_exact(handle, nonce_len)
        cipher_len = struct.unpack(">I", _read_exact(handle, 4))[0]
        ciphertext = _read_exact(handle, cipher_len)
        yield EncryptedBlobRaw(nonce=nonce, ciphertext=ciphertext, key_id=None)


LEGACY_DERIVE_PURPOSES = {
    "entity_tokens": ["tokenization"],
}


class DerivedKeyProvider:
    def __init__(self, keyring: KeyRing, purpose: str) -> None:
        self._keyring = keyring
        self._purpose = purpose

    def active(self) -> tuple[str, bytes]:
        key_id, root = self._keyring.active_key(self._purpose)
        return key_id, derive_key(root, self._purpose)

    def for_id(self, key_id: str) -> bytes:
        root = self._keyring.key_for(self._purpose, key_id)
        return derive_key(root, self._purpose)

    def _purpose_variants(self) -> list[str]:
        legacy = LEGACY_DERIVE_PURPOSES.get(self._purpose, [])
        return [self._purpose, *legacy]

    def candidates(self, key_id: str | None) -> list[bytes]:
        keys: list[bytes] = []
        seen: set[str] = set()
        if key_id:
            try:
                root = self._keyring.key_for(self._purpose, key_id)
                for purpose in self._purpose_variants():
                    keys.append(derive_key(root, purpose))
                seen.add(key_id)
            except KeyError:
                pass
        active_id, active_root = self._keyring.active_key(self._purpose)
        if active_id not in seen:
            for purpose in self._purpose_variants():
                keys.append(derive_key(active_root, purpose))
            seen.add(active_id)
        for key_id, root in self._keyring.all_keys(self._purpose).items():
            if key_id in seen:
                continue
            for purpose in self._purpose_variants():
                keys.append(derive_key(root, purpose))
            seen.add(key_id)
        return keys


class EncryptedJSONStore:
    def __init__(
        self,
        root_dir: str,
        key_provider: DerivedKeyProvider,
        run_id: str,
        *,
        require_decrypt: bool = False,
        fsync_policy: str = _FsyncPolicy.NONE,
    ) -> None:
        self._root = root_dir
        self._key_provider = key_provider
        self._require_decrypt = require_decrypt
        self._run_id = run_id or "run"
        self._fsync_policy = fsync_policy
        self._index: dict[str, str] = {}
        self._count_cache: int | None = None
        os.makedirs(self._root, exist_ok=True)

    def _path_for_write(self, record_id: str, ts_utc: str | None, record_type: str | None = None) -> str:
        shard_dir = _shard_dir(
            self._root,
            self._run_id,
            ts_utc,
            record_id=record_id,
            record_type=record_type,
        )
        safe = _encode_record_id(record_id)
        return os.path.join(shard_dir, f"{safe}.json")

    def _path_candidates(self, record_id: str) -> list[str]:
        paths: list[str] = []
        if record_id in self._index:
            cached = self._index[record_id]
            if os.path.exists(cached):
                return [cached]
            self._index.pop(record_id, None)
        encoded = _encode_record_id(record_id)
        run_dir = os.path.join(self._root, _encode_record_id(self._run_id))
        if os.path.isdir(run_dir):
            for current, _dirs, files in os.walk(run_dir):
                if f"{encoded}.json" in files:
                    path = os.path.join(current, f"{encoded}.json")
                    self._index[record_id] = path
                    return [path]
        if os.path.isdir(self._root):
            for current, _dirs, files in os.walk(self._root):
                if f"{encoded}.json" in files:
                    path = os.path.join(current, f"{encoded}.json")
                    self._index[record_id] = path
                    return [path]
        paths.append(os.path.join(self._root, f"{encoded}.json"))
        legacy = _legacy_safe_id(record_id)
        paths.append(os.path.join(self._root, f"{legacy}.json"))
        return paths

    def _remove_existing(self, record_id: str) -> None:
        for path in self._path_candidates(record_id):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _write(self, record_id: str, value: Any) -> None:
        payload = json.dumps(value, sort_keys=True).encode("utf-8")
        key_id, key = self._key_provider.active()
        blob = encrypt_bytes(key, payload, key_id=key_id)
        ts_utc = _extract_ts(value)
        record_type = value.get("record_type") if isinstance(value, dict) else None
        path = self._path_for_write(record_id, ts_utc, record_type)
        _atomic_write_json(path, blob.__dict__, fsync_policy=self._fsync_policy)
        self._index[record_id] = path

    def put(self, record_id: str, value: Any) -> None:
        self.put_replace(record_id, value)

    def put_replace(self, record_id: str, value: Any) -> None:
        existed = any(os.path.exists(path) for path in self._path_candidates(record_id))
        self._remove_existing(record_id)
        self._write(record_id, value)
        if self._count_cache is not None and not existed:
            self._count_cache += 1

    def put_new(self, record_id: str, value: Any) -> None:
        for path in self._path_candidates(record_id):
            if os.path.exists(path):
                raise FileExistsError(f"Metadata record already exists: {record_id}")
        self._write(record_id, value)
        if self._count_cache is not None:
            self._count_cache += 1

    def get(self, record_id: str, default: Any = None) -> Any:
        for path in self._path_candidates(record_id):
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            blob = EncryptedBlob(**data)
            payload = None
            for key in self._key_provider.candidates(blob.key_id):
                try:
                    payload = decrypt_bytes(key, blob)
                    break
                except Exception:
                    continue
            if payload is None:
                if self._require_decrypt:
                    raise RuntimeError(f"Decrypt failed for metadata record {record_id}")
                return default
            return json.loads(payload.decode("utf-8"))
        return default

    def keys(self) -> list[str]:
        ids: set[str] = set()
        for path in _iter_files(self._root, [".json"]):
            filename = os.path.basename(path)
            if not filename.endswith(".json"):
                continue
            token = filename[:-5]
            ids.add(_decode_record_id(token))
        return sorted(ids)

    def count(self) -> int:
        if self._count_cache is None:
            self._count_cache = len(list(_iter_files(self._root, [".json"])))
        return self._count_cache

    def query_time_window(
        self,
        start_ts: str | None,
        end_ts: str | None,
        limit: int | None = None,
    ) -> list[str]:
        start_key = _parse_ts(start_ts).timestamp() if start_ts else None
        end_key = _parse_ts(end_ts).timestamp() if end_ts else None
        matched: list[tuple[float, str]] = []
        for record_id in self.keys():
            try:
                record = self.get(record_id)
            except RuntimeError:
                continue
            if not isinstance(record, dict):
                continue
            ts_val = _extract_ts(record)
            if not ts_val:
                continue
            ts_key = _parse_ts(ts_val).timestamp()
            if start_key is not None and ts_key < start_key:
                continue
            if end_key is not None and ts_key > end_key:
                continue
            matched.append((ts_key, record_id))
        matched.sort(key=lambda item: (item[0], item[1]))
        if limit is not None:
            matched = matched[: int(limit)]
        return [record_id for _ts, record_id in matched]

    def delete(self, record_id: str) -> bool:
        removed = False
        for path in self._path_candidates(record_id):
            if os.path.exists(path):
                try:
                    os.remove(path)
                    removed = True
                except OSError:
                    continue
        if removed:
            self._index.pop(record_id, None)
            if self._count_cache is not None and self._count_cache > 0:
                self._count_cache -= 1
        return removed

    def rotate(self, _new_key: bytes | None = None) -> int:
        count = 0
        for record_id in self.keys():
            try:
                value = self.get(record_id)
            except RuntimeError:
                continue
            if value is None:
                continue
            self.put(record_id, value)
            count += 1
        return count


class EncryptedBlobStore:
    def __init__(
        self,
        root_dir: str,
        key_provider: DerivedKeyProvider,
        run_id: str,
        *,
        require_decrypt: bool = False,
        fsync_policy: str = _FsyncPolicy.NONE,
    ) -> None:
        self._root = root_dir
        self._key_provider = key_provider
        self._require_decrypt = require_decrypt
        self._run_id = run_id or "run"
        self._fsync_policy = fsync_policy
        self._index: dict[str, str] = {}
        self._count_cache: int | None = None
        os.makedirs(self._root, exist_ok=True)

    def _path_for_write(self, record_id: str, ts_utc: str | None, *, stream: bool) -> str:
        shard_dir = _shard_dir(
            self._root,
            self._run_id,
            ts_utc,
            record_id=record_id,
        )
        safe = _encode_record_id(record_id)
        ext = STREAM_EXT if stream else BLOB_EXT
        return os.path.join(shard_dir, f"{safe}{ext}")

    def _path_candidates(self, record_id: str) -> list[str]:
        paths: list[str] = []
        if record_id in self._index:
            cached = self._index[record_id]
            if os.path.exists(cached):
                return [cached]
            self._index.pop(record_id, None)
        encoded = _encode_record_id(record_id)
        run_dir = os.path.join(self._root, _encode_record_id(self._run_id))
        if os.path.isdir(run_dir):
            for current, _dirs, files in os.walk(run_dir):
                for ext in (BLOB_EXT, STREAM_EXT):
                    name = f"{encoded}{ext}"
                    if name in files:
                        path = os.path.join(current, name)
                        self._index[record_id] = path
                        return [path]
        if os.path.isdir(self._root):
            for current, _dirs, files in os.walk(self._root):
                for ext in (BLOB_EXT, STREAM_EXT):
                    name = f"{encoded}{ext}"
                    if name in files:
                        path = os.path.join(current, name)
                        self._index[record_id] = path
                        return [path]
        paths.append(os.path.join(self._root, f"{encoded}{BLOB_EXT}"))
        paths.append(os.path.join(self._root, f"{encoded}{STREAM_EXT}"))
        legacy = _legacy_safe_id(record_id)
        paths.append(os.path.join(self._root, f"{legacy}.json"))
        paths.append(os.path.join(self._root, f"{legacy}.jsonl"))
        return paths

    def _remove_existing(self, record_id: str) -> None:
        for path in self._path_candidates(record_id):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def put(self, record_id: str, data: bytes, *, ts_utc: str | None = None) -> None:
        self.put_replace(record_id, data, ts_utc=ts_utc)

    def put_replace(self, record_id: str, data: bytes, *, ts_utc: str | None = None) -> None:
        key_id, key = self._key_provider.active()
        blob = encrypt_bytes_raw(key, data, key_id=key_id)
        path = self._path_for_write(record_id, ts_utc, stream=False)
        existed = any(os.path.exists(path) for path in self._path_candidates(record_id))
        self._remove_existing(record_id)
        _atomic_write_bytes(path, _pack_blob(blob), fsync_policy=self._fsync_policy)
        self._index[record_id] = path
        if self._count_cache is not None and not existed:
            self._count_cache += 1

    def put_new(self, record_id: str, data: bytes, *, ts_utc: str | None = None) -> None:
        for path in self._path_candidates(record_id):
            if os.path.exists(path):
                raise FileExistsError(f"Blob record already exists: {record_id}")
        self.put_replace(record_id, data, ts_utc=ts_utc)

    def put_stream(self, record_id: str, stream, chunk_size: int = 1024 * 1024, *, ts_utc: str | None = None) -> None:
        for path in self._path_candidates(record_id):
            if os.path.exists(path):
                raise FileExistsError(f"Blob record already exists: {record_id}")
        self.put_stream_replace(record_id, stream, chunk_size=chunk_size, ts_utc=ts_utc)

    def put_stream_replace(
        self,
        record_id: str,
        stream,
        chunk_size: int = 1024 * 1024,
        *,
        ts_utc: str | None = None,
    ) -> None:
        key_id, key = self._key_provider.active()
        path = self._path_for_write(record_id, ts_utc, stream=True)
        existed = any(os.path.exists(path) for path in self._path_candidates(record_id))
        self._remove_existing(record_id)
        tmp_path = f"{path}.tmp"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp_path, "wb") as handle:
            handle.write(STREAM_MAGIC)
            key_id_bytes = key_id.encode("utf-8") if key_id else b""
            handle.write(struct.pack(">H", len(key_id_bytes)))
            if key_id_bytes:
                handle.write(key_id_bytes)
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                blob = encrypt_bytes_raw(key, chunk, key_id=key_id)
                handle.write(struct.pack(">H", len(blob.nonce)))
                handle.write(blob.nonce)
                handle.write(struct.pack(">I", len(blob.ciphertext)))
                handle.write(blob.ciphertext)
            _fsync_file(handle, self._fsync_policy)
        os.replace(tmp_path, path)
        _fsync_dir(path, self._fsync_policy)
        self._index[record_id] = path
        if self._count_cache is not None and not existed:
            self._count_cache += 1

    def get(self, record_id: str, default: bytes | None = None) -> bytes | None:
        for path in self._path_candidates(record_id):
            if not os.path.exists(path):
                continue
            if path.endswith(BLOB_EXT):
                with open(path, "rb") as handle:
                    try:
                        blob_raw = _unpack_blob(handle)
                    except Exception:
                        continue
                for key in self._key_provider.candidates(blob_raw.key_id):
                    try:
                        return decrypt_bytes_raw(key, blob_raw)
                    except Exception:
                        continue
                if self._require_decrypt:
                    raise RuntimeError(f"Decrypt failed for blob record {record_id}")
                return default
            if path.endswith(STREAM_EXT):
                with open(path, "rb") as handle:
                    try:
                        key_id, offset = _read_stream_header(handle)
                    except Exception:
                        continue
                    candidates = self._key_provider.candidates(key_id)
                    for key in candidates:
                        try:
                            handle.seek(offset)
                            payload = bytearray()
                            for chunk in _iter_stream_chunks(handle):
                                payload.extend(decrypt_bytes_raw(key, chunk))
                            return bytes(payload)
                        except Exception:
                            continue
                if self._require_decrypt:
                    raise RuntimeError(f"Decrypt failed for blob record {record_id}")
                return default
            if path.endswith(".json"):
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                blob_json = EncryptedBlob(**data)
                for key in self._key_provider.candidates(blob_json.key_id):
                    try:
                        return decrypt_bytes(key, blob_json)
                    except Exception:
                        continue
                if self._require_decrypt:
                    raise RuntimeError(f"Decrypt failed for blob record {record_id}")
                return default
            if path.endswith(".jsonl"):
                with open(path, "r", encoding="utf-8") as handle:
                    header_line = handle.readline()
                    if not header_line:
                        if self._require_decrypt:
                            raise RuntimeError(f"Decrypt failed for blob record {record_id}")
                        return default
                    header = json.loads(header_line)
                    key_id = header.get("key_id")
                    key_candidates = self._key_provider.candidates(key_id)
                    for key in key_candidates:
                        try:
                            handle.seek(0)
                            handle.readline()
                            payload = bytearray()
                            for line in handle:
                                line = line.strip()
                                if not line:
                                    continue
                                chunk_data = json.loads(line)
                                blob_json = EncryptedBlob(**chunk_data)
                                payload.extend(decrypt_bytes(key, blob_json))
                            return bytes(payload)
                        except Exception:
                            continue
                if self._require_decrypt:
                    raise RuntimeError(f"Decrypt failed for blob record {record_id}")
                return default
        return default

    def keys(self) -> list[str]:
        ids: set[str] = set()
        for path in _iter_files(self._root, [BLOB_EXT, STREAM_EXT, ".json", ".jsonl"]):
            filename = os.path.basename(path)
            for ext in (BLOB_EXT, STREAM_EXT, ".json", ".jsonl"):
                if filename.endswith(ext):
                    token = filename[: -len(ext)]
                    ids.add(_decode_record_id(token))
                    break
        return sorted(ids)

    def delete(self, record_id: str) -> bool:
        removed = False
        for path in self._path_candidates(record_id):
            if os.path.exists(path):
                try:
                    os.remove(path)
                    removed = True
                except OSError:
                    continue
        if removed:
            self._index.pop(record_id, None)
            if self._count_cache is not None and self._count_cache > 0:
                self._count_cache -= 1
        return removed

    def rotate(self, _new_key: bytes | None = None) -> int:
        count = 0
        for record_id in self.keys():
            value = self.get(record_id)
            if value is None:
                continue
            self.put(record_id, value)
            count += 1
        return count

    def count(self) -> int:
        if self._count_cache is None:
            self._count_cache = len(self.keys())
        return self._count_cache


class EntityMapStore:
    def __init__(
        self,
        root_dir: str,
        key_provider: DerivedKeyProvider,
        persist: bool,
        *,
        require_decrypt: bool = False,
        fsync_policy: str = _FsyncPolicy.NONE,
    ) -> None:
        self._root = root_dir
        self._key_provider = key_provider
        self._persist = persist
        self._require_decrypt = require_decrypt
        self._fsync_policy = fsync_policy
        os.makedirs(self._root, exist_ok=True)
        self._path = os.path.join(self._root, "entity_map.json")
        self._data: dict[str, dict[str, Any]] = {}
        if self._persist and os.path.exists(self._path):
            self._data = self._load()

    def _load(self) -> dict[str, dict[str, str]]:
        with open(self._path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        blob = EncryptedBlob(**payload)
        decrypted = None
        for key in self._key_provider.candidates(blob.key_id):
            try:
                decrypted = decrypt_bytes(key, blob)
                break
            except Exception:
                continue
        if decrypted is None:
            if self._require_decrypt:
                raise RuntimeError("Decrypt failed for entity map")
            return {}
        return json.loads(decrypted.decode("utf-8"))

    def _save(self) -> None:
        payload = json.dumps(self._data, sort_keys=True).encode("utf-8")
        key_id, key = self._key_provider.active()
        blob = encrypt_bytes(key, payload, key_id=key_id)
        _atomic_write_json(self._path, blob.__dict__, fsync_policy=self._fsync_policy)

    def put(
        self,
        token: str,
        value: str,
        kind: str,
        *,
        key_id: str | None = None,
        key_version: int | None = None,
        first_seen_ts: str | None = None,
    ) -> None:
        record: dict[str, Any] = {"value": value, "kind": kind}
        if key_id:
            record["key_id"] = key_id
        if key_version is not None:
            record["key_version"] = int(key_version)
        if first_seen_ts:
            record["first_seen_ts"] = first_seen_ts
        self._data[token] = record
        if self._persist:
            self._save()

    def get(self, token: str) -> dict[str, Any] | None:
        return self._data.get(token)

    def items(self) -> dict[str, dict[str, Any]]:
        return dict(self._data)

    def rotate(self, _new_key: bytes | None = None) -> int:
        if self._persist:
            self._save()
            return 1
        return 0


class EncryptedStoragePlugin(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        storage_cfg = context.config.get("storage", {})
        crypto_cfg = storage_cfg.get("crypto", {})
        keyring_path = crypto_cfg.get("keyring_path", "data/vault/keyring.json")
        root_key_path = crypto_cfg.get("root_key_path", "data/vault/root.key")
        encryption_required = storage_cfg.get("encryption_required", False)
        require_protection = bool(encryption_required and os.name == "nt")
        keyring = KeyRing.load(keyring_path, legacy_root_path=root_key_path, require_protection=require_protection)
        self._keyring = keyring
        meta_provider = DerivedKeyProvider(keyring, "metadata")
        media_provider = DerivedKeyProvider(keyring, "media")
        entity_provider = DerivedKeyProvider(keyring, "entity_tokens")
        data_dir = storage_cfg.get("data_dir", "data")
        run_id = str(context.config.get("runtime", {}).get("run_id", "run"))
        fsync_policy = _FsyncPolicy.normalize(storage_cfg.get("fsync_policy"))
        require_decrypt = bool(encryption_required)
        self._metadata = ImmutableMetadataStore(
            EncryptedJSONStore(
                os.path.join(data_dir, "metadata"),
                meta_provider,
                run_id,
                require_decrypt=require_decrypt,
                fsync_policy=fsync_policy,
            )
        )
        self._media = EncryptedBlobStore(
            os.path.join(data_dir, "media"),
            media_provider,
            run_id,
            require_decrypt=require_decrypt,
            fsync_policy=fsync_policy,
        )
        persist = storage_cfg.get("entity_map", {}).get("persist", True)
        self._entity_map = EntityMapStore(
            os.path.join(data_dir, "entity_map"),
            entity_provider,
            persist,
            require_decrypt=require_decrypt,
            fsync_policy=fsync_policy,
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "storage.metadata": self._metadata,
            "storage.media": self._media,
            "storage.entity_map": self._entity_map,
            "storage.keyring": self._keyring,
        }


def create_plugin(plugin_id: str, context: PluginContext) -> EncryptedStoragePlugin:
    return EncryptedStoragePlugin(plugin_id, context)
