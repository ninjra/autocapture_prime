from __future__ import annotations

import tempfile
from pathlib import Path

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.retrieval_basic.plugin import RetrievalStrategy, _scan_metadata


class _Store:
    def __init__(self, records: dict[str, dict]) -> None:
        self._records = dict(records)

    def get(self, key: str, default=None):
        return self._records.get(key, default)

    def keys(self):
        return list(self._records.keys())

    def latest(self, record_type: str, limit: int = 100):
        out: list[dict] = []
        for record_id in sorted(self._records.keys(), reverse=True):
            record = self._records[record_id]
            if str(record.get("record_type") or "") != str(record_type):
                continue
            out.append({"record_id": record_id, "record": record})
            if len(out) >= int(limit):
                break
        return out


def test_scan_metadata_matches_window_projection_without_text() -> None:
    store = _Store(
        {
            "run1/evidence.window.meta/1": {
                "record_type": "evidence.window.meta",
                "ts_utc": "2026-02-22T01:02:03Z",
                "window": {
                    "title": "SiriusXM - Chill Instrumental",
                    "process_path": "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
                },
            }
        }
    )
    results = _scan_metadata(store, "siriusxm", None, None)
    assert len(results) == 1
    assert results[0]["record_id"] == "run1/evidence.window.meta/1"
    assert "SiriusXM" in str(results[0].get("snippet") or "")


def test_retrieval_latest_scan_on_miss_returns_projection_hits() -> None:
    record_id = "run1/evidence.window.meta/1"
    store = _Store(
        {
            record_id: {
                "record_type": "evidence.window.meta",
                "ts_utc": "2026-02-22T01:02:03Z",
                "window": {
                    "title": "Remote Desktop Web Client",
                    "process_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                },
            }
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        cfg = {
            "storage": {
                "lexical_path": str(Path(tmp) / "lexical.db"),
                "vector_path": str(Path(tmp) / "vector.db"),
            },
            "indexing": {"vector_backend": "sqlite"},
            "retrieval": {
                "vector_enabled": False,
                "allow_full_scan": False,
                "latest_scan_on_miss": True,
                "latest_scan_limit": 100,
            },
        }

        def _cap(name: str):
            if name == "storage.metadata":
                return store
            return None

        ctx = PluginContext(config=cfg, get_capability=_cap, logger=lambda _m, _p=None: None)
        retrieval = RetrievalStrategy("retrieval", ctx)
        results = retrieval.search("remote desktop", time_window=None)
        assert len(results) == 1
        assert str(results[0].get("record_id") or "") == record_id
        trace = retrieval.trace()
        assert any(str(item.get("tier") or "") == "LATEST_SCAN" for item in trace)


def test_retrieval_latest_scan_uses_latest_record_payload_without_get_roundtrip() -> None:
    record_id = "run1/evidence.window.meta/1"

    class _StoreLatestOnly(_Store):
        def get(self, key: str, default=None):  # noqa: ARG002
            raise AssertionError("latest-scan should use row['record'] payload")

    store = _StoreLatestOnly(
        {
            record_id: {
                "record_type": "evidence.window.meta",
                "ts_utc": "2026-02-22T01:02:03Z",
                "window": {
                    "title": "SiriusXM Discover",
                    "process_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                },
            }
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        cfg = {
            "storage": {
                "lexical_path": str(Path(tmp) / "lexical.db"),
                "vector_path": str(Path(tmp) / "vector.db"),
            },
            "indexing": {"vector_backend": "sqlite"},
            "retrieval": {
                "vector_enabled": False,
                "allow_full_scan": False,
                "latest_scan_on_miss": True,
                "latest_scan_limit": 100,
            },
        }

        def _cap(name: str):
            if name == "storage.metadata":
                return store
            return None

        ctx = PluginContext(config=cfg, get_capability=_cap, logger=lambda _m, _p=None: None)
        retrieval = RetrievalStrategy("retrieval", ctx)
        results = retrieval.search("siriusxm", time_window=None)
        assert len(results) == 1
        assert str(results[0].get("record_id") or "") == record_id


def test_retrieval_trace_includes_perf_histogram() -> None:
    store = _Store(
        {
            "run1/evidence.window.meta/1": {
                "record_type": "evidence.window.meta",
                "ts_utc": "2026-02-22T01:02:03Z",
                "window": {"title": "SiriusXM"},
            }
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        cfg = {
            "storage": {
                "lexical_path": str(Path(tmp) / "lexical.db"),
                "vector_path": str(Path(tmp) / "vector.db"),
            },
            "indexing": {"vector_backend": "sqlite"},
            "retrieval": {
                "vector_enabled": False,
                "allow_full_scan": False,
                "latest_scan_on_miss": True,
                "latest_scan_limit": 100,
            },
        }

        def _cap(name: str):
            if name == "storage.metadata":
                return store
            return None

        ctx = PluginContext(config=cfg, get_capability=_cap, logger=lambda _m, _p=None: None)
        retrieval = RetrievalStrategy("retrieval", ctx)
        _ = retrieval.search("siriusxm", time_window=None)
        trace = retrieval.trace()
        perf_rows = [row for row in trace if str(row.get("tier") or "") == "PERF"]
        assert len(perf_rows) == 1
        perf = perf_rows[0]
        assert float(perf.get("search_ms", 0.0) or 0.0) >= 0.0
        assert int(perf.get("records_scanned", 0) or 0) >= 1
        hist = perf.get("latency_histogram_ms", {})
        assert isinstance(hist, dict) and bool(hist)
