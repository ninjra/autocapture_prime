from __future__ import annotations

import math
import struct
import unittest

from plugins.builtin.audio_windows.plugin import (
    _audio_fingerprint_features,
    _build_audio_fingerprint_record,
    _encode_wav,
)


class AudioFingerprintTests(unittest.TestCase):
    def _sine_pcm16(self, *, hz: float, seconds: float, sample_rate: int) -> bytes:
        total = int(seconds * sample_rate)
        out: list[int] = []
        for idx in range(total):
            val = int(round(12000.0 * math.sin((2.0 * math.pi * hz * idx) / float(sample_rate))))
            out.append(max(-32768, min(32767, val)))
        return struct.pack("<" + ("h" * len(out)), *out)

    def test_audio_fingerprint_features_wav(self) -> None:
        sr = 16000
        raw = self._sine_pcm16(hz=440.0, seconds=0.25, sample_rate=sr)
        wav = _encode_wav(raw, sr, 1)
        features = _audio_fingerprint_features(
            encoded_bytes=wav,
            encoding="wav",
            sample_rate=sr,
            channels=1,
        )
        self.assertEqual(features.get("schema_version"), 1)
        self.assertGreater(int(features.get("sample_count", 0)), 0)
        self.assertGreater(int(features.get("duration_ms", 0)), 100)
        self.assertEqual(len(features.get("envelope", [])), 8)

    def test_audio_fingerprint_record_is_deterministic(self) -> None:
        sr = 16000
        raw = self._sine_pcm16(hz=1000.0, seconds=0.2, sample_rate=sr)
        wav = _encode_wav(raw, sr, 1)
        one_id, one = _build_audio_fingerprint_record(
            record_id="run/audio/1",
            ts_utc="2026-02-18T00:00:00Z",
            run_id="run",
            encoded_bytes=wav,
            encoding="wav",
            sample_rate=sr,
            channels=1,
            producer_plugin_id="builtin.capture.audio_windows",
            source="loopback",
            parent_hash="abc123",
        )
        two_id, two = _build_audio_fingerprint_record(
            record_id="run/audio/1",
            ts_utc="2026-02-18T00:00:00Z",
            run_id="run",
            encoded_bytes=wav,
            encoding="wav",
            sample_rate=sr,
            channels=1,
            producer_plugin_id="builtin.capture.audio_windows",
            source="loopback",
            parent_hash="abc123",
        )
        self.assertEqual(one_id, two_id)
        self.assertIsInstance(one, dict)
        self.assertIsInstance(two, dict)
        assert one is not None and two is not None
        self.assertEqual(one.get("record_type"), "derived.audio.fingerprint")
        self.assertEqual(one.get("content_hash"), two.get("content_hash"))
        self.assertEqual(one.get("payload_hash"), two.get("payload_hash"))
        provenance = one.get("provenance", {})
        self.assertEqual(provenance.get("stage_id"), "audio.fingerprint")
        self.assertEqual(provenance.get("plugin_id"), "builtin.capture.audio_windows")


if __name__ == "__main__":
    unittest.main()
