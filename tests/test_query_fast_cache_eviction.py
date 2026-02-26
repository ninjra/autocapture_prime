from __future__ import annotations

from unittest import mock

import autocapture_nx.kernel.query as query_mod


def _cache_count() -> int:
    return int(len(query_mod._QUERY_FAST_CACHE))


def test_query_fast_cache_put_sweeps_expired_entries_without_direct_get() -> None:
    query_mod._QUERY_FAST_CACHE.clear()
    query_mod._QUERY_FAST_CACHE["old"] = {
        "ts_monotonic": 1.0,
        "payload": {"answer": "stale"},
        "payload_bytes": 24,
    }
    with mock.patch("autocapture_nx.kernel.query.time.monotonic", return_value=100.0):
        query_mod._query_fast_cache_put(
            "new",
            {"answer": "fresh"},
            ttl_s=1.0,
            max_entries=16,
            max_total_bytes=1024 * 1024,
            max_entry_bytes=64 * 1024,
        )
    assert "old" not in query_mod._QUERY_FAST_CACHE
    assert "new" in query_mod._QUERY_FAST_CACHE
    assert _cache_count() == 1


def test_query_fast_cache_put_skips_oversized_payload() -> None:
    query_mod._QUERY_FAST_CACHE.clear()
    oversized = {"blob": "x" * 10000}
    query_mod._query_fast_cache_put(
        "big",
        oversized,
        ttl_s=30.0,
        max_entries=16,
        max_total_bytes=1024 * 1024,
        max_entry_bytes=1024,
    )
    assert "big" not in query_mod._QUERY_FAST_CACHE
    assert _cache_count() == 0


def test_query_fast_cache_put_enforces_total_bytes_budget_by_lru_ts() -> None:
    query_mod._QUERY_FAST_CACHE.clear()
    with mock.patch("autocapture_nx.kernel.query.time.monotonic", side_effect=[1.0, 2.0]):
        query_mod._query_fast_cache_put(
            "k1",
            {"blob": "a" * 50000},
            ttl_s=60.0,
            max_entries=16,
            max_total_bytes=70000,
            max_entry_bytes=128 * 1024,
        )
        query_mod._query_fast_cache_put(
            "k2",
            {"blob": "b" * 50000},
            ttl_s=60.0,
            max_entries=16,
            max_total_bytes=70000,
            max_entry_bytes=128 * 1024,
        )
    assert "k1" not in query_mod._QUERY_FAST_CACHE
    assert "k2" in query_mod._QUERY_FAST_CACHE
    assert _cache_count() == 1
