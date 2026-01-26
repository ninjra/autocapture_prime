"""Windows input tracking plugin using pynput."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class InputTrackerWindows(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._stop = threading.Event()
        self._listener = None
        self._last_event_ts = None

    def capabilities(self) -> dict[str, Any]:
        return {"tracking.input": self}

    def last_event_ts(self) -> float | None:
        return self._last_event_ts

    def idle_seconds(self) -> float:
        if self._last_event_ts is None:
            return float("inf")
        return max(0.0, time.time() - self._last_event_ts)

    def start(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Input tracking supported on Windows only")
        try:
            from pynput import keyboard, mouse
        except Exception as exc:
            raise RuntimeError(f"Missing input dependency: {exc}")

        event_builder = self.context.get_capability("event.builder")
        mode = self.context.config.get("capture", {}).get("input_tracking", {}).get("mode", "raw")
        if mode == "off":
            return

        def on_key_press(key):
            ts = datetime.now(timezone.utc).isoformat()
            self._last_event_ts = time.time()
            event_builder.journal_event(
                "input.key",
                {"key": str(key), "action": "press"} if mode == "raw" else {"action": "press"},
                ts_utc=ts,
            )

        def on_click(x, y, button, pressed):
            ts = datetime.now(timezone.utc).isoformat()
            self._last_event_ts = time.time()
            payload = {"button": str(button), "pressed": pressed}
            if mode == "raw":
                payload["x"] = int(x)
                payload["y"] = int(y)
            event_builder.journal_event(
                "input.mouse",
                payload,
                ts_utc=ts,
            )

        self._listener = {
            "keyboard": keyboard.Listener(on_press=on_key_press),
            "mouse": mouse.Listener(on_click=on_click),
        }
        self._listener["keyboard"].start()
        self._listener["mouse"].start()

    def stop(self) -> None:
        if self._listener:
            self._listener["keyboard"].stop()
            self._listener["mouse"].stop()
            self._listener = None


def create_plugin(plugin_id: str, context: PluginContext) -> InputTrackerWindows:
    return InputTrackerWindows(plugin_id, context)
