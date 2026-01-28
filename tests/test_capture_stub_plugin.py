import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.capture_stub.plugin import CaptureStub


class _MediaStore:
    def __init__(self) -> None:
        self.records: list[tuple[str, bytes]] = []

    def put_stream(self, record_id: str, stream, chunk_size: int = 1024 * 1024, *, ts_utc: str | None = None) -> None:
        _ = chunk_size
        _ = ts_utc
        self.records.append((record_id, stream.read()))


class _MetaStore:
    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    def put_new(self, key: str, value: dict) -> None:
        if key in self.data:
            raise FileExistsError(key)
        self.data[key] = value

    def put(self, key: str, value: dict) -> None:
        self.data[key] = value


class _EventBuilder:
    def __init__(self) -> None:
        self.ledger = []
        self.journal = []

    def policy_snapshot_hash(self) -> str:
        return "policyhash"

    def journal_event(self, _event_type: str, payload: dict, **_kwargs) -> str:
        self.journal.append(payload)
        return _kwargs.get("event_id") or "event_id"

    def ledger_entry(self, _stage: str, inputs: list[str], outputs: list[str], *, payload: dict | None = None, **_kwargs) -> str:
        _ = (inputs, outputs)
        self.ledger.append(payload or {})
        return "hash"


class _Backpressure:
    def adjust(self, _metrics: dict, state: dict) -> dict:
        return {"fps_target": state["fps_target"], "bitrate_kbps": state["bitrate_kbps"]}


class _Logger:
    def log(self, _event: str, _payload: dict) -> None:
        return None


class CaptureStubPluginTests(unittest.TestCase):
    def test_stub_capture_generates_segments(self) -> None:
        media = _MediaStore()
        meta = _MetaStore()
        event_builder = _EventBuilder()
        backpressure = _Backpressure()
        logger = _Logger()

        with tempfile.TemporaryDirectory() as tmp:
            frames_dir = Path(tmp) / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            try:
                from PIL import Image
            except Exception:
                self.skipTest("Pillow not installed")

            img = Image.new("RGB", (64, 64), (200, 180, 160))
            img.save(frames_dir / "frame1.jpg", format="JPEG", quality=90)

            config = {
                "capture": {
                    "video": {
                        "backend": "mss",
                        "segment_seconds": 1,
                        "fps_target": 30,
                        "container": "avi_mjpeg",
                        "encoder": "cpu",
                        "jpeg_quality": 90,
                        "monitor_index": 0,
                    },
                    "stub": {
                        "frames_dir": str(frames_dir),
                        "loop": False,
                        "max_frames": 2,
                        "frame_width": 64,
                        "frame_height": 64,
                        "jpeg_quality": 90,
                    },
                },
                "storage": {"spool_dir": tmp, "data_dir": tmp},
                "backpressure": {"max_fps": 30, "max_bitrate_kbps": 8000, "max_queue_depth": 5},
                "runtime": {"run_id": "run1", "timezone": "UTC"},
            }

            def get_capability(name: str):
                mapping = {
                    "storage.media": media,
                    "storage.metadata": meta,
                    "event.builder": event_builder,
                    "capture.backpressure": backpressure,
                    "observability.logger": logger,
                }
                return mapping[name]

            ctx = PluginContext(config=config, get_capability=get_capability, logger=lambda _m: None)
            plugin = CaptureStub("capture.stub", ctx)
            plugin.start()
            if plugin._thread is not None:
                plugin._thread.join(timeout=5)
            plugin.stop()

            self.assertTrue(media.records)
            self.assertTrue(meta.data)


if __name__ == "__main__":
    unittest.main()
