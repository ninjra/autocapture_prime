import tempfile
import unittest

from autocapture.research.cache import ResearchCache
from autocapture.research.scout import ResearchScout, ResearchSource, Watchlist


class ResearchScoutCacheTests(unittest.TestCase):
    def test_cache_and_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = ResearchCache(tmp)
            source = ResearchSource("source1", [{"id": "a", "title": "Alpha"}])
            watchlist = Watchlist(tags=[])
            scout = ResearchScout(source, watchlist, cache)

            report1 = scout.run(threshold=0.1)
            self.assertFalse(report1["cache_hit"])

            report2 = scout.run(threshold=0.1)
            self.assertTrue(report2["cache_hit"])

            source.items.append({"id": "b", "title": "Beta"})
            report3 = scout.run(threshold=0.1)
            self.assertTrue(report3["diff"]["changed"])


if __name__ == "__main__":
    unittest.main()
