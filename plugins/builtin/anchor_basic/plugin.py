"""Anchor writer plugin for ledger head hashes."""

from __future__ import annotations

import base64
import os
from datetime import datetime, timezone
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class AnchorWriter(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        storage_cfg = context.config.get("storage", {})
        anchor_cfg = storage_cfg.get("anchor", {})
        self._path = anchor_cfg.get("path", os.path.join("data_anchor", "anchors.ndjson"))
        self._use_dpapi = bool(anchor_cfg.get("use_dpapi", os.name == "nt"))
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._seq = 0
        if os.path.exists(self._path):
            with open(self._path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    self._seq += 1

    def capabilities(self) -> dict[str, Any]:
        return {"anchor.writer": self}

    def anchor(self, ledger_head_hash: str) -> dict[str, Any]:
        record = {
            "anchor_seq": self._seq,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "ledger_head_hash": ledger_head_hash,
        }
        payload = dumps(record).encode("utf-8")
        if self._use_dpapi and os.name == "nt":
            try:
                from autocapture_nx.windows.dpapi import protect

                payload = protect(payload)
                payload = b"DPAPI:" + base64.b64encode(payload)
            except Exception:
                payload = dumps(record).encode("utf-8")
        with open(self._path, "a", encoding="utf-8") as handle:
            handle.write(payload.decode("utf-8") + "\n")
        self._seq += 1
        return record


def create_plugin(plugin_id: str, context: PluginContext) -> AnchorWriter:
    return AnchorWriter(plugin_id, context)
