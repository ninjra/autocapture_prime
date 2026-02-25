from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from autocapture.promptops.engine import PromptStore


class PromptStoreCacheBoundsTests(unittest.TestCase):
    def test_prompt_store_cache_is_bounded_and_lru(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PromptStore(Path(tmp), cache_max_entries=3)
            store.set("a", "A")
            store.set("b", "B")
            store.set("c", "C")
            self.assertEqual(len(store._cache), 3)  # noqa: SLF001
            _ = store.get("a")
            store.set("d", "D")
            self.assertEqual(len(store._cache), 3)  # noqa: SLF001
            self.assertIn("a", store._cache)  # noqa: SLF001
            self.assertIn("c", store._cache)  # noqa: SLF001
            self.assertIn("d", store._cache)  # noqa: SLF001
            self.assertNotIn("b", store._cache)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
