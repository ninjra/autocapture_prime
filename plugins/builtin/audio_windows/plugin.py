"""Windows audio capture plugin using sounddevice (WASAPI loopback if available)."""

from __future__ import annotations

import io
import os
import queue
import threading
import subprocess
import wave
import hashlib
import shutil
from dataclasses import dataclass, field
from typing import Any

from autocapture_nx.kernel.hashing import sha256_canonical
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
        storage_meta = self.context.get_capability("storage.metadata")
        event_builder = self.context.get_capability("event.builder")

        audio_cfg = self.context.config.get("capture", {}).get("audio", {})
        mode = _resolve_audio_mode(audio_cfg)
        if mode == "off":
            return
        samplerate = int(audio_cfg.get("sample_rate", 44100))
        channels = int(audio_cfg.get("channels", 2))
        blocksize = int(audio_cfg.get("blocksize", samplerate))
        encoding = str(audio_cfg.get("encoding", "wav"))
        ffmpeg_path = str(audio_cfg.get("ffmpeg_path", "")).strip()
        device = audio_cfg.get("device")
        device_name = None
        if device is not None:
            try:
                info = sd.query_devices(device)
                if isinstance(info, dict):
                    device_name = info.get("name")
            except Exception:
                device_name = None
        seq = 0
        run_id = ensure_run_id(self.context.config)
        audio_buffer = _AudioBuffer(max_queue=self.context.config.get("capture", {}).get("audio", {}).get("queue_max", 8))

        callback = self._build_callback(audio_buffer, sd.CallbackStop)

        stream_kwargs = {
            "samplerate": samplerate,
            "channels": channels,
            "callback": callback,
            "blocksize": blocksize,
            "dtype": "int16",
        }
        if mode == "loopback":
            try:
                stream_kwargs["extra_settings"] = sd.WasapiSettings(loopback=True)
            except Exception:
                pass
        device = audio_cfg.get("device")
        if device is not None:
            stream_kwargs["device"] = device

        with sd.InputStream(**stream_kwargs):
            while not self._stop.is_set():
                try:
                    data, frames, time_info = audio_buffer.queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                dropped = audio_buffer.consume_drops()
                if dropped > 0:
                    _record_audio_drop(
                        event_builder,
                        {
                            "dropped": int(dropped),
                            "queue_max": int(audio_buffer.max_queue),
                            "policy": "drop_newest",
                            "source": mode,
                        },
                    )
                record_id = prefixed_id(run_id, "audio", seq)
                ts_utc = _iso_utc()
                encoded_bytes, encoding_used = _encode_audio_bytes(
                    data,
                    samplerate=samplerate,
                    channels=channels,
                    encoding=encoding,
                    ffmpeg_path=ffmpeg_path,
                )
                if hasattr(storage_media, "put_new"):
                    storage_media.put_new(record_id, encoded_bytes, ts_utc=ts_utc)
                else:
                    storage_media.put(record_id, encoded_bytes, ts_utc=ts_utc)
                payload = {
                    "record_type": "derived.audio.segment",
                    "ts_utc": ts_utc,
                    "run_id": run_id,
                    "frames": int(frames),
                    "channels": int(channels),
                    "sample_rate": int(samplerate),
                    "encoding": encoding_used,
                    "source": mode,
                    "device": device,
                    "device_name": device_name,
                    "drops": {"count": int(dropped), "queue_max": int(audio_buffer.max_queue), "policy": "drop_newest"},
                    "content_hash": hashlib.sha256(encoded_bytes).hexdigest(),
                }
                payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
                if hasattr(storage_meta, "put_new"):
                    storage_meta.put_new(record_id, payload)
                else:
                    storage_meta.put(record_id, payload)
                event_builder.journal_event("capture.audio", payload, event_id=record_id, ts_utc=ts_utc)
                event_builder.ledger_entry(
                    "audio.capture",
                    inputs=[],
                    outputs=[record_id],
                    payload=payload,
                    entry_id=record_id,
                    ts_utc=ts_utc,
                )
                seq += 1
        while not audio_buffer.queue.empty():
            try:
                data, frames, time_info = audio_buffer.queue.get_nowait()
            except queue.Empty:
                break
            dropped = audio_buffer.consume_drops()
            if dropped > 0:
                _record_audio_drop(
                    event_builder,
                    {
                        "dropped": int(dropped),
                        "queue_max": int(audio_buffer.max_queue),
                        "policy": "drop_newest",
                        "source": mode,
                    },
                )
            record_id = prefixed_id(run_id, "audio", seq)
            ts_utc = _iso_utc()
            encoded_bytes, encoding_used = _encode_audio_bytes(
                data,
                samplerate=samplerate,
                channels=channels,
                encoding=encoding,
                ffmpeg_path=ffmpeg_path,
            )
            if hasattr(storage_media, "put_new"):
                storage_media.put_new(record_id, encoded_bytes, ts_utc=ts_utc)
            else:
                storage_media.put(record_id, encoded_bytes, ts_utc=ts_utc)
            payload = {
                "record_type": "derived.audio.segment",
                "ts_utc": ts_utc,
                "run_id": run_id,
                "frames": int(frames),
                "channels": int(channels),
                "sample_rate": int(samplerate),
                "encoding": encoding_used,
                "source": mode,
                "device": device,
                "device_name": device_name,
                "drops": {"count": int(dropped), "queue_max": int(audio_buffer.max_queue), "policy": "drop_newest"},
                "content_hash": hashlib.sha256(encoded_bytes).hexdigest(),
            }
            payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
            if hasattr(storage_meta, "put_new"):
                storage_meta.put_new(record_id, payload)
            else:
                storage_meta.put(record_id, payload)
            event_builder.journal_event("capture.audio", payload, event_id=record_id, ts_utc=ts_utc)
            event_builder.ledger_entry(
                "audio.capture",
                inputs=[],
                outputs=[record_id],
                payload=payload,
                entry_id=record_id,
                ts_utc=ts_utc,
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


def _record_audio_drop(event_builder: Any, payload: dict[str, Any]) -> None:
    if event_builder is None:
        return
    try:
        event_builder.journal_event("audio.drop", payload)
        event_builder.ledger_entry(
            "audio.drop",
            inputs=[],
            outputs=[],
            payload=payload,
        )
    except Exception:
        return


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

    def consume_drops(self) -> int:
        dropped = int(self.dropped)
        self.dropped = 0
        return dropped


def _resolve_audio_mode(audio_cfg: dict[str, Any]) -> str:
    if audio_cfg.get("enabled") is False:
        return "off"
    mode = str(audio_cfg.get("mode", "auto")).lower()
    if mode in ("off", "disabled"):
        return "off"
    if mode in ("mic", "microphone"):
        return "microphone"
    if mode in ("loopback", "system"):
        return "loopback"
    if audio_cfg.get("system_audio", False):
        return "loopback"
    if audio_cfg.get("microphone", False):
        return "microphone"
    return "off"


def _encode_audio_bytes(
    raw: bytes,
    *,
    samplerate: int,
    channels: int,
    encoding: str,
    ffmpeg_path: str | None = None,
) -> tuple[bytes, str]:
    encoding = encoding.lower()
    if encoding in ("pcm16", "raw"):
        return raw, "pcm16"
    if encoding in ("wav", "wav_pcm16"):
        return _encode_wav(raw, samplerate, channels), "wav"
    if encoding in ("flac", "opus"):
        path = ffmpeg_path or shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
        if not path:
            raise RuntimeError(f"ffmpeg required for {encoding} audio encoding")
        return _encode_with_ffmpeg(raw, samplerate, channels, encoding, path), encoding
    raise ValueError(f"Unsupported audio encoding: {encoding}")


def _encode_wav(raw: bytes, samplerate: int, channels: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(int(channels))
        handle.setsampwidth(2)
        handle.setframerate(int(samplerate))
        handle.writeframes(raw)
    return buffer.getvalue()


def _encode_with_ffmpeg(raw: bytes, samplerate: int, channels: int, encoding: str, ffmpeg_path: str) -> bytes:
    if encoding == "flac":
        codec = "flac"
        fmt = "flac"
    else:
        codec = "libopus"
        fmt = "opus"
    cmd = [
        ffmpeg_path,
        "-y",
        "-f",
        "s16le",
        "-ar",
        str(int(samplerate)),
        "-ac",
        str(int(channels)),
        "-i",
        "pipe:0",
        "-c:a",
        codec,
        "-f",
        fmt,
        "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate(raw, timeout=20)
    if proc.returncode != 0:
        message = stderr.decode(errors="ignore") if stderr else ""
        raise RuntimeError(f"ffmpeg audio encoding failed: {message[:200]}")
    return stdout
