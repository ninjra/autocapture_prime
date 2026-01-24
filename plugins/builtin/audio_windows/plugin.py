"""Windows audio capture plugin using sounddevice (WASAPI loopback if available)."""

from __future__ import annotations

import os
import threading
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class AudioCaptureWindows(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def capabilities(self) -> dict[str, Any]:
        return {"capture.audio": self}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Audio capture supported on Windows only")
        try:
            import sounddevice as sd
        except Exception as exc:
            raise RuntimeError(f"Missing audio dependency: {exc}")

        storage_media = self.context.get_capability("storage.media")
        journal = self.context.get_capability("journal.writer")

        samplerate = 44100
        channels = 2
        blocksize = 44100
        seq = 0

        def callback(indata, frames, time_info, status):
            nonlocal seq
            if self._stop.is_set():
                raise sd.CallbackStop()
            data = indata.tobytes()
            record_id = f"audio_{seq}"
            storage_media.put(record_id, data)
            journal.append(
                {
                    "schema_version": 1,
                    "event_id": record_id,
                    "sequence": seq,
                    "ts_utc": time_info.inputBufferAdcTime and str(time_info.inputBufferAdcTime) or "",
                    "tzid": "UTC",
                    "offset_minutes": 0,
                    "event_type": "capture.audio",
                    "payload": {"frames": frames, "channels": channels, "samplerate": samplerate},
                }
            )
            seq += 1

        with sd.InputStream(samplerate=samplerate, channels=channels, callback=callback, blocksize=blocksize):
            while not self._stop.is_set():
                sd.sleep(200)


def create_plugin(plugin_id: str, context: PluginContext) -> AudioCaptureWindows:
    return AudioCaptureWindows(plugin_id, context)
