"""Ledger writer plugin with hash chaining."""

from __future__ import annotations

import json
import os
import hashlib
import errno
import tempfile
import threading
from dataclasses import dataclass
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


@dataclass(frozen=True)
class LedgerEntryV1:
    record_type: str
    schema_version: int
    entry_id: str
    ts_utc: str
    stage: str
    inputs: list[str]
    outputs: list[str]
    policy_snapshot_hash: str
    payload: dict[str, Any]
    prev_hash: str | None
    entry_hash: str


class LedgerWriter(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        data_dir = context.config.get("storage", {}).get("data_dir", "data")
        os.makedirs(data_dir, exist_ok=True)
        self._path = os.path.join(data_dir, "ledger.ndjson")
        self._last_hash = None
        self._lock = threading.Lock()
        self._load_last_hash()

    def _is_perm_error(self, exc: BaseException) -> bool:
        if isinstance(exc, PermissionError):
            return True
        if isinstance(exc, OSError):
            return exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS)
        return False

    def _fallback_path(self) -> str:
        digest = hashlib.sha256(self._path.encode("utf-8")).hexdigest()[:16]
        root = os.path.join(tempfile.gettempdir(), "autocapture", "shadow_logs")
        os.makedirs(root, exist_ok=True)
        return os.path.join(root, f"{digest}.ledger.ndjson")

    def _use_fallback_path(self) -> None:
        fallback = self._fallback_path()
        if fallback != self._path:
            self._path = fallback

    def _load_last_hash(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    text = line.strip()
                    if " " in text and text.split(" ", 1)[0].isalnum():
                        try:
                            entry = text.split(" ", 1)[1]
                            self._last_hash = hashlib.sha256(entry.encode("utf-8")).hexdigest()
                            continue
                        except Exception:
                            pass
                    try:
                        entry = json.loads(text)
                        self._last_hash = entry.get("entry_hash", self._last_hash)
                    except Exception:
                        continue
        except Exception as exc:
            if self._is_perm_error(exc):
                self._use_fallback_path()
                return
            raise

    def capabilities(self) -> dict[str, Any]:
        return {"ledger.writer": self}

    def append(self, entry: dict[str, Any]) -> str:
        required = {
            "record_type",
            "schema_version",
            "entry_id",
            "ts_utc",
            "stage",
            "inputs",
            "outputs",
            "policy_snapshot_hash",
        }
        missing = required - set(entry.keys())
        if missing:
            raise ValueError(f"Ledger entry missing fields: {sorted(missing)}")
        with self._lock:
            payload = dict(entry)
            prev_hash = self._last_hash
            payload["prev_hash"] = prev_hash
            payload.pop("entry_hash", None)
            canonical = dumps(payload)
            tail = prev_hash or ""
            entry_hash = hashlib.sha256((canonical + tail).encode("utf-8")).hexdigest()
            payload["entry_hash"] = entry_hash
            try:
                with open(self._path, "a", encoding="utf-8") as handle:
                    handle.write(f"{dumps(payload)}\n")
                    try:
                        handle.flush()
                        os.fsync(handle.fileno())
                    except OSError:
                        pass
            except Exception as exc:
                if not self._is_perm_error(exc):
                    raise
                self._use_fallback_path()
                with open(self._path, "a", encoding="utf-8") as handle:
                    handle.write(f"{dumps(payload)}\n")
                    try:
                        handle.flush()
                        os.fsync(handle.fileno())
                    except OSError:
                        pass
            self._last_hash = entry_hash
            return entry_hash

    def head_hash(self) -> str | None:
        return self._last_hash

    def verify(self) -> tuple[bool, list[str]]:
        from autocapture.pillars.citable import verify_ledger

        return verify_ledger(self._path)


def create_plugin(plugin_id: str, context: PluginContext) -> LedgerWriter:
    return LedgerWriter(plugin_id, context)
