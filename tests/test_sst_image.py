import io
import unittest

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency guard
    Image = None

from autocapture_nx.processing.sst.image import normalize_image, tile_image


@unittest.skipIf(Image is None, "Pillow is required for SST image tests")
class SSTImageTests(unittest.TestCase):
    def test_normalize_image_outputs_hashes(self) -> None:
        assert Image is not None
        img = Image.new("RGB", (128, 64), (255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        normalized = normalize_image(buf.getvalue())
        self.assertEqual(normalized.width, 128)
        self.assertEqual(normalized.height, 64)
        self.assertEqual(len(normalized.phash), 64)
        self.assertEqual(len(normalized.image_sha256), 64)

    def test_tile_refine_adds_focus_patches(self) -> None:
        assert Image is not None
        img = Image.new("RGB", (200, 120), (240, 240, 240))
        tokens = [
            {"bbox": (20, 20, 30, 30), "confidence_bp": 1000},
            {"bbox": (28, 22, 38, 32), "confidence_bp": 1200},
        ]
        tiles = tile_image(
            img,
            tile_max_px=100,
            overlap_px=10,
            add_full_frame=True,
            focus_tokens=tokens,
            focus_conf_bp=5000,
            focus_padding_px=5,
            focus_max_patches=4,
            focus_cluster_gap_px=12,
        )
        focus_tiles = [tile for tile in tiles if str(tile.get("patch_id", "")).startswith("focus-")]
        self.assertTrue(focus_tiles)
        for tile in focus_tiles:
            x1, y1, x2, y2 = tile["bbox"]
            self.assertGreaterEqual(x1, 0)
            self.assertGreaterEqual(y1, 0)
            self.assertLessEqual(x2, 200)
            self.assertLessEqual(y2, 120)


if __name__ == "__main__":
    unittest.main()
