"""Ledger writer plugin with hash chaining."""

from __future__ import annotations

import json
import os
import hashlib
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class LedgerWriter(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        data_dir = context.config.get("storage", {}).get("data_dir", "data")
        os.makedirs(data_dir, exist_ok=True)
        self._path = os.path.join(data_dir, "ledger.ndjson")
        self._last_hash = None
        if os.path.exists(self._path):
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

    def capabilities(self) -> dict[str, Any]:
        return {"ledger.writer": self}

    def append(self, entry: dict[str, Any]) -> str:
        required = {"schema_version", "entry_id", "ts_utc", "stage", "inputs", "outputs", "policy_snapshot_hash"}
        missing = required - set(entry.keys())
        if missing:
            raise ValueError(f"Ledger entry missing fields: {sorted(missing)}")
        payload = dict(entry)
        prev_hash = self._last_hash
        payload["prev_hash"] = prev_hash
        payload.pop("entry_hash", None)
        canonical = dumps(payload)
        tail = prev_hash or ""
        entry_hash = hashlib.sha256((canonical + tail).encode("utf-8")).hexdigest()
        payload["entry_hash"] = entry_hash
        with open(self._path, "a", encoding="utf-8") as handle:
            handle.write(f"{dumps(payload)}\n")
        self._last_hash = entry_hash
        return entry_hash


def create_plugin(plugin_id: str, context: PluginContext) -> LedgerWriter:
    return LedgerWriter(plugin_id, context)
