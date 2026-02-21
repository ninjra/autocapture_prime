"""Anomaly detector for state edges (deterministic thresholding)."""

from __future__ import annotations

from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.kernel.hashing import sha256_text


class AnomalyDetector(PluginBase):
    VERSION = "0.1.0"

    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"state.anomaly": self}

    def detect(self, edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cfg = self.context.config if isinstance(self.context.config, dict) else {}
        state_cfg = cfg.get("processing", {}).get("state_layer", {}) if isinstance(cfg.get("processing", {}), dict) else {}
        anomaly_cfg = state_cfg.get("anomaly", {}) if isinstance(state_cfg.get("anomaly", {}), dict) else {}
        threshold = float(anomaly_cfg.get("pred_error_threshold", 0.4) or 0.4)
        max_alerts = int(anomaly_cfg.get("max_alerts_per_run", 25) or 25)
        candidates: list[tuple[float, int, str, str]] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            pred_error = float(edge.get("pred_error", 0.0) or 0.0)
            if pred_error < threshold:
                continue
            edge_id = str(edge.get("edge_id") or "")
            prov = edge.get("provenance", {}) if isinstance(edge.get("provenance"), dict) else {}
            try:
                ts_ms = int(prov.get("created_ts_ms", 0) or 0)
            except Exception:
                ts_ms = 0
            model_version = str(prov.get("model_version") or "")
            candidates.append((pred_error, ts_ms, edge_id, model_version))

        candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        alerts: list[dict[str, Any]] = []
        for pred_error, ts_ms, edge_id, model_version in candidates:
            if max_alerts > 0 and len(alerts) >= max_alerts:
                break
            if edge_id:
                alert_id = sha256_text(f"{edge_id}:{model_version}:{threshold}")
            else:
                alert_id = sha256_text(f"{pred_error}:{model_version}:{threshold}:{ts_ms}")
            alerts.append(
                {
                    "alert_id": alert_id,
                    "edge_id": edge_id,
                    "pred_error": pred_error,
                    "ts_ms": ts_ms,
                    "severity": "high" if pred_error >= threshold * 1.5 else "medium",
                }
            )
        return alerts
