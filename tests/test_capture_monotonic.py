import tempfile
import unittest
from unittest.mock import patch

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.windows.win_capture import Frame
from plugins.builtin.capture_windows import plugin as capture_mod


class _MediaStore:
    def __init__(self) -> None:
        self.records: list[tuple[str, bytes]] = []

    def put_stream(self, record_id: str, stream, chunk_size: int = 1024 * 1024) -> None:
        _ = chunk_size
        self.records.append((record_id, stream.read()))


class _MetaStore:
    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    def put(self, key: str, value: dict) -> None:
        self.data[key] = value


class _EventBuilder:
    def journal_event(self, _event_type: str, _payload: dict, **_kwargs) -> str:
        return "event"

    def ledger_entry(self, _stage: str, inputs: list[str], outputs: list[str], **_kwargs) -> str:
        _ = (inputs, outputs)
        return "hash"


class _Backpressure:
    def adjust(self, _metrics: dict, state: dict) -> dict:
        return {"fps_target": state["fps_target"], "bitrate_kbps": state["bitrate_kbps"]}


class _Logger:
    def log(self, _event: str, _payload: dict) -> None:
        return None


class CaptureMonotonicTests(unittest.TestCase):
    def test_segment_duration_uses_monotonic(self) -> None:
        frames = [
            Frame(ts_utc="t0", data=b"x", width=1, height=1),
            Frame(ts_utc="t1", data=b"y", width=1, height=1),
            Frame(ts_utc="t2", data=b"z", width=1, height=1),
        ]

        def fake_iter_screenshots(_fps_provider):
            for frame in frames:
                yield frame

        monotonic_values = iter([0.0, 1.0, 12.0, 13.0, 14.0])

        def fake_monotonic() -> float:
            return next(monotonic_values, 1.4)


        media = _MediaStore()
        meta = _MetaStore()
        event_builder = _EventBuilder()
        backpressure = _Backpressure()
        logger = _Logger()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "capture": {"video": {"backend": "mss", "segment_seconds": 10, "fps_target": 30}},
                "storage": {"spool_dir": tmpdir, "data_dir": tmpdir},
                "backpressure": {"max_fps": 30, "max_bitrate_kbps": 8000},
                "runtime": {"run_id": "run1", "timezone": "UTC"},
            }
            caps = {
                "storage.media": media,
                "storage.metadata": meta,
                "event.builder": event_builder,
                "capture.backpressure": backpressure,
                "observability.logger": logger,
            }
            ctx = PluginContext(config=config, get_capability=lambda k: caps[k], logger=lambda _m: None)
            plugin = capture_mod.CaptureWindows("capture", ctx)

            with patch.object(capture_mod, "iter_screenshots", side_effect=lambda fps_provider: fake_iter_screenshots(fps_provider)):
                with patch.object(capture_mod.time, "monotonic", side_effect=fake_monotonic):
                    plugin._run_loop()

        self.assertEqual(len(media.records), 2)
        self.assertEqual(media.records[0][0], "run1/segment/0")
        self.assertEqual(media.records[1][0], "run1/segment/1")


if __name__ == "__main__":
    unittest.main()
