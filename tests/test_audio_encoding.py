import unittest

from plugins.builtin.audio_windows.plugin import _encode_audio_bytes, _resolve_audio_mode


class AudioEncodingTests(unittest.TestCase):
    def test_audio_mode_resolution(self) -> None:
        self.assertEqual(_resolve_audio_mode({"enabled": False}), "off")
        self.assertEqual(_resolve_audio_mode({"system_audio": True}), "loopback")
        self.assertEqual(_resolve_audio_mode({"microphone": True, "system_audio": False}), "microphone")

    def test_pcm_passthrough(self) -> None:
        raw = b"\x00\x01" * 10
        encoded, kind = _encode_audio_bytes(raw, samplerate=44100, channels=1, encoding="pcm16", ffmpeg_path=None)
        self.assertEqual(kind, "pcm16")
        self.assertEqual(encoded, raw)

    def test_wav_encoding(self) -> None:
        raw = b"\x00\x01" * 100
        encoded, kind = _encode_audio_bytes(raw, samplerate=44100, channels=1, encoding="wav", ffmpeg_path=None)
        self.assertEqual(kind, "wav")
        self.assertTrue(encoded.startswith(b"RIFF"))
        self.assertIn(b"WAVE", encoded[:32])


if __name__ == "__main__":
    unittest.main()
