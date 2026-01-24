"""Observability logger with evidence redaction."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class ObservabilityLogger(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        data_dir = context.config.get("storage", {}).get("data_dir", "data")
        self._log_path = os.path.join(data_dir, "logs", "observability.log")
        os.makedirs(os.path.dirname(self._log_path), exist_ok=True)

    def capabilities(self) -> dict[str, Any]:
        return {"observability.logger": self}

    def log(self, event: str, data: dict[str, Any]) -> None:
        obs_cfg = self.context.config.get("observability", {})
        allow_evidence = obs_cfg.get("allow_evidence", False)
        allowlist = set(obs_cfg.get("allowlist_keys", []))

        payload = {"event": event, "ts": datetime.now(timezone.utc).isoformat()}
        if allow_evidence:
            payload.update(data)
        else:
            for key, value in data.items():
                if key in allowlist:
                    payload[key] = value
                else:
                    payload[key] = "<redacted>"

        with open(self._log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")


def create_plugin(plugin_id: str, context: PluginContext) -> ObservabilityLogger:
    return ObservabilityLogger(plugin_id, context)
