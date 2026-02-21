import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.audio_windows.plugin import AudioCaptureWindows, _AudioBuffer


class _DummyInput:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def tobytes(self) -> bytes:
        return self._data


class AudioCallbackQueueTests(unittest.TestCase):
    def test_callback_enqueues_without_blocking(self) -> None:
        ctx = PluginContext(config={}, get_capability=lambda _k: None, logger=lambda _m: None)
        plugin = AudioCaptureWindows("audio", ctx)
        buffer = _AudioBuffer(max_queue=1)
        callback = plugin._build_callback(buffer, RuntimeError)

        callback(_DummyInput(b"a"), 4, {}, None)
        callback(_DummyInput(b"b"), 2, {}, None)
        self.assertEqual(buffer.queue.qsize(), 1)
        self.assertEqual(buffer.dropped, 1)
        data, frames, _info = buffer.queue.get_nowait()
        self.assertEqual(data, b"a")
        self.assertEqual(frames, 4)


if __name__ == "__main__":
    unittest.main()
