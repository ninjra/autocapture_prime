import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.audio_windows.plugin import AudioCaptureWindows


class _DummyBuffer:
    def __init__(self) -> None:
        self.calls = 0
        self.last = None

    def enqueue(self, data, frames, time_info) -> None:
        self.calls += 1
        self.last = (data, frames, time_info)


class _DummyInData:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def tobytes(self) -> bytes:
        return self._payload


class AudioCallbackQueueTests(unittest.TestCase):
    def test_callback_enqueues_only(self) -> None:
        ctx = PluginContext(config={}, get_capability=lambda _k: None, logger=lambda _m: None)
        plugin = AudioCaptureWindows("audio", ctx)
        buffer = _DummyBuffer()

        class DummyStop(Exception):
            pass

        callback = plugin._build_callback(buffer, DummyStop)
        callback(_DummyInData(b"abc"), frames=3, time_info=None, status=None)

        self.assertEqual(buffer.calls, 1)
        self.assertEqual(buffer.last[0], b"abc")


if __name__ == "__main__":
    unittest.main()
