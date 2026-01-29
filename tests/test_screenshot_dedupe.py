import unittest

from autocapture_nx.capture.screenshot import ScreenshotDeduper, hash_bytes


class ScreenshotDedupeTests(unittest.TestCase):
    def test_dedupe_skips_duplicates(self) -> None:
        deduper = ScreenshotDeduper(enabled=True, hash_algo="sha256")
        data = b"frame-bytes"
        fp = hash_bytes(data, algo="sha256")
        store, duplicate = deduper.should_store(fp, now=0.0)
        self.assertTrue(store)
        self.assertFalse(duplicate)
        deduper.mark_saved(fp, now=0.0)
        store, duplicate = deduper.should_store(fp, now=1.0)
        self.assertFalse(store)
        self.assertTrue(duplicate)

    def test_force_interval_allows_periodic_store(self) -> None:
        deduper = ScreenshotDeduper(enabled=True, hash_algo="blake2b", force_interval_s=10)
        data = b"frame-bytes"
        fp = hash_bytes(data, algo="blake2b")
        store, duplicate = deduper.should_store(fp, now=0.0)
        self.assertTrue(store)
        self.assertFalse(duplicate)
        deduper.mark_saved(fp, now=0.0)
        store, duplicate = deduper.should_store(fp, now=5.0)
        self.assertFalse(store)
        self.assertTrue(duplicate)
        store, duplicate = deduper.should_store(fp, now=11.0)
        self.assertTrue(store)
        self.assertTrue(duplicate)


if __name__ == "__main__":
    unittest.main()
