import unittest
from dataclasses import dataclass

from autocapture_nx.capture.pipeline import FrameDeduper


@dataclass
class DummyFrame:
    data: bytes
    ts_monotonic: float | None = None


class CaptureThroughputBaselineTests(unittest.TestCase):
    def test_deduper_marks_duplicates_within_window(self) -> None:
        dedupe = FrameDeduper(
            {
                "enabled": True,
                "mode": "mark_only",
                "hash": "blake2b",
                "sample_bytes": 64,
                "min_repeat": 1,
                "window_ms": 1500,
            }
        )
        a = DummyFrame(b"x" * 1024, ts_monotonic=1.0)
        b = DummyFrame(b"x" * 1024, ts_monotonic=1.1)
        c = DummyFrame(b"y" * 1024, ts_monotonic=1.2)
        r1 = dedupe.check(a)
        r2 = dedupe.check(b)
        r3 = dedupe.check(c)
        self.assertFalse(r1.duplicate)
        self.assertTrue(r2.duplicate)
        self.assertFalse(r3.duplicate)


if __name__ == "__main__":
    unittest.main()

