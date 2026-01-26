import unittest

from autocapture.ingest.normalizer import normalize_bbox


class SpanBboxNormTests(unittest.TestCase):
    def test_bbox_normalization(self) -> None:
        bbox = (10, 20, 30, 40)
        norm = normalize_bbox(bbox, width=100, height=200)
        self.assertAlmostEqual(norm["x0"], 0.1)
        self.assertAlmostEqual(norm["y0"], 0.1)
        self.assertAlmostEqual(norm["x1"], 0.4)
        self.assertAlmostEqual(norm["y1"], 0.3)
        for key in ("x0", "y0", "x1", "y1"):
            self.assertGreaterEqual(norm[key], 0.0)
            self.assertLessEqual(norm[key], 1.0)


if __name__ == "__main__":
    unittest.main()
