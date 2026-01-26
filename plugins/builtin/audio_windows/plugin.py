"""Windows audio capture plugin using sounddevice (WASAPI loopback if available)."""

from __future__ import annotations

import os
import queue
import threading
from dataclasses import dataclass, field
from typing import Any

from autocapture_nx.kernel.ids import ensure_run_id, prefixed_id
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
        event_builder = self.context.get_capability("event.builder")

        samplerate = 44100
        channels = 2
        blocksize = 44100
        seq = 0
        run_id = ensure_run_id(self.context.config)
        audio_buffer = _AudioBuffer(max_queue=self.context.config.get("capture", {}).get("audio", {}).get("queue_max", 8))

        callback = self._build_callback(audio_buffer, sd.CallbackStop)

        with sd.InputStream(samplerate=samplerate, channels=channels, callback=callback, blocksize=blocksize):
            while not self._stop.is_set():
                try:
                    data, frames, time_info = audio_buffer.queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                record_id = prefixed_id(run_id, "audio", seq)
                if hasattr(storage_media, "put_new"):
                    storage_media.put_new(record_id, data, ts_utc=_iso_utc())
                else:
                    storage_media.put(record_id, data, ts_utc=_iso_utc())
                event_builder.journal_event(
                    "capture.audio",
                    {"frames": int(frames), "channels": int(channels), "samplerate": int(samplerate)},
                    event_id=record_id,
                    ts_utc=_iso_utc(),
                )
                seq += 1
        while not audio_buffer.queue.empty():
            try:
                data, frames, time_info = audio_buffer.queue.get_nowait()
            except queue.Empty:
                break
            record_id = prefixed_id(run_id, "audio", seq)
            if hasattr(storage_media, "put_new"):
                storage_media.put_new(record_id, data, ts_utc=_iso_utc())
            else:
                storage_media.put(record_id, data, ts_utc=_iso_utc())
            event_builder.journal_event(
                "capture.audio",
                {"frames": int(frames), "channels": int(channels), "samplerate": int(samplerate)},
                event_id=record_id,
                ts_utc=_iso_utc(),
            )
            seq += 1

    def _build_callback(self, audio_buffer: "_AudioBuffer", stop_exc) -> Any:
        def callback(indata, frames, time_info, status):
            if self._stop.is_set():
                raise stop_exc()
            audio_buffer.enqueue(indata.tobytes(), frames, time_info)

        return callback


def create_plugin(plugin_id: str, context: PluginContext) -> AudioCaptureWindows:
    return AudioCaptureWindows(plugin_id, context)


def _iso_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


@dataclass
class _AudioBuffer:
    max_queue: int
    queue: queue.Queue = field(init=False)
    dropped: int = 0

    def __post_init__(self) -> None:
        self.queue = queue.Queue(maxsize=int(self.max_queue))

    def enqueue(self, data: bytes, frames: int, time_info: Any) -> None:
        try:
            self.queue.put_nowait((data, frames, time_info))
        except queue.Full:
            self.dropped += 1
