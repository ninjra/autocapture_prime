import unittest

from autocapture.ingest.spans import build_span


class SpanIdsStableTests(unittest.TestCase):
    def test_span_id_deterministic(self) -> None:
        span1 = build_span("hello", {"x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.4}, {"source": "test"})
        span2 = build_span("hello", {"x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.4}, {"source": "test"})
        self.assertEqual(span1.span_id, span2.span_id)

    def test_span_id_changes(self) -> None:
        span1 = build_span("hello", None, {"source": "test"})
        span2 = build_span("hello", None, {"source": "other"})
        self.assertNotEqual(span1.span_id, span2.span_id)


if __name__ == "__main__":
    unittest.main()
