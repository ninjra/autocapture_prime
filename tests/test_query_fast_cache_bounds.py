from __future__ import annotations

import unittest

from autocapture_nx.kernel.query import _query_fast_cache_settings


class _System:
    def __init__(self, config):
        self.config = config


class QueryFastCacheBoundsTests(unittest.TestCase):
    def test_max_entries_has_upper_bound(self) -> None:
        system = _System({"query": {"fast_cache": {"enabled": True, "ttl_s": 1.0, "max_entries": 999999}}})
        enabled, ttl_s, max_entries = _query_fast_cache_settings(system)
        self.assertTrue(enabled)
        self.assertEqual(ttl_s, 1.0)
        self.assertEqual(max_entries, 4096)

    def test_max_entries_has_lower_bound(self) -> None:
        system = _System({"query": {"fast_cache": {"enabled": True, "ttl_s": 1.0, "max_entries": 0}}})
        _enabled, _ttl_s, max_entries = _query_fast_cache_settings(system)
        self.assertEqual(max_entries, 1)


if __name__ == "__main__":
    unittest.main()
