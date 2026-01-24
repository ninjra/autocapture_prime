"""Deterministic backpressure controller with hysteresis."""

from __future__ import annotations

import time
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class BackpressureController(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._last_change = 0.0

    def capabilities(self) -> dict[str, Any]:
        return {"capture.backpressure": self}

    def adjust(self, metrics: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
        cfg = self.context.config.get("backpressure", {})
        now = metrics.get("now", time.time())
        if now - self._last_change < cfg.get("hysteresis_s", 10):
            return current

        queue_depth = metrics.get("queue_depth", 0)
        min_fps = cfg.get("min_fps", 5)
        max_fps = cfg.get("max_fps", 30)
        min_bitrate = cfg.get("min_bitrate_kbps", 1000)
        max_bitrate = cfg.get("max_bitrate_kbps", 8000)
        max_step_fps = cfg.get("max_step_fps", 5)
        max_step_bitrate = cfg.get("max_step_bitrate_kbps", 1000)
        max_queue = cfg.get("max_queue_depth", 5)

        fps = current.get("fps_target", max_fps)
        bitrate = current.get("bitrate_kbps", max_bitrate)

        if queue_depth > max_queue:
            fps = max(min_fps, fps - max_step_fps)
            bitrate = max(min_bitrate, bitrate - max_step_bitrate)
            self._last_change = now
        elif queue_depth == 0:
            fps = min(max_fps, fps + max_step_fps)
            bitrate = min(max_bitrate, bitrate + max_step_bitrate)
            self._last_change = now

        return {"fps_target": fps, "bitrate_kbps": bitrate}


def create_plugin(plugin_id: str, context: PluginContext) -> BackpressureController:
    return BackpressureController(plugin_id, context)
