from __future__ import annotations

import os
import tempfile
from pathlib import Path

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.retrieval_basic.plugin import RetrievalStrategy, _scan_metadata, _scan_metadata_latest


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


def test_retrieval_latest_scan_limit_env_override_applies() -> None:
    store = _Store(
        {
            "run1/evidence.window.meta/2": {
                "record_type": "evidence.window.meta",
                "ts_utc": "2026-02-22T01:02:04Z",
                "window": {"title": "Remote Desktop Web Client"},
            },
            "run1/evidence.window.meta/1": {
                "record_type": "evidence.window.meta",
                "ts_utc": "2026-02-22T01:02:03Z",
                "window": {"title": "Remote Desktop Web Client"},
            },
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
        prev = os.environ.get("AUTOCAPTURE_RETRIEVAL_LATEST_SCAN_LIMIT")
        try:
            os.environ["AUTOCAPTURE_RETRIEVAL_LATEST_SCAN_LIMIT"] = "1"
            results = retrieval.search("remote desktop", time_window=None)
        finally:
            if prev is None:
                os.environ.pop("AUTOCAPTURE_RETRIEVAL_LATEST_SCAN_LIMIT", None)
            else:
                os.environ["AUTOCAPTURE_RETRIEVAL_LATEST_SCAN_LIMIT"] = prev
        assert len(results) <= 1
        trace = retrieval.trace()
        latest_rows = [row for row in trace if str(row.get("tier") or "") == "LATEST_SCAN"]
        assert latest_rows and int(latest_rows[0].get("limit", 0) or 0) == 1


def test_retrieval_latest_scan_uses_single_pass_for_expensive_filtered_latest() -> None:
    calls: list[str | None] = []

    class _ExpensiveStore(_Store):
        _latest_filtered_expensive = True

        def latest(self, record_type: str | None, limit: int = 100):  # type: ignore[override]
            calls.append(record_type)
            out: list[dict] = []
            for record_id in sorted(self._records.keys(), reverse=True):
                record = self._records[record_id]
                if record_type is not None and str(record.get("record_type") or "") != str(record_type):
                    continue
                out.append({"record_id": record_id, "record": record})
                if len(out) >= int(limit):
                    break
            return out

    store = _ExpensiveStore(
        {
            "run1/derived.text.ocr/2": {
                "record_type": "derived.text.ocr",
                "ts_utc": "2026-02-22T01:02:05Z",
                "text": "NCAAW game starts at 8:00 PM",
            },
            "run1/evidence.window.meta/1": {
                "record_type": "evidence.window.meta",
                "ts_utc": "2026-02-22T01:02:03Z",
                "window": {"title": "Remote Desktop Web Client"},
            },
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
                "attach_timelines": False,
            },
        }

        def _cap(name: str):
            if name == "storage.metadata":
                return store
            return None

        ctx = PluginContext(config=cfg, get_capability=_cap, logger=lambda _m, _p=None: None)
        retrieval = RetrievalStrategy("retrieval", ctx)
        results = retrieval.search("ncaaw", time_window=None)
        assert len(results) == 1
        assert calls
        assert calls[0] is None
        assert all(call is None for call in calls)


def test_scan_metadata_latest_enforces_budget_and_reason(monkeypatch) -> None:
    class _Store:
        def latest(self, record_type: str | None, limit: int = 100):  # noqa: ARG002
            out: list[dict] = []
            for idx in range(int(limit)):
                out.append(
                    {
                        "record_id": f"run1/derived.text.ocr/{idx:04d}",
                        "record": {
                            "record_type": "derived.text.ocr",
                            "ts_utc": "2026-02-22T01:02:03Z",
                            "text": f"row {idx}",
                        },
                    }
                )
            return out

    ticks = {"value": 0.0}

    def _fake_perf_counter() -> float:
        ticks["value"] += 0.02
        return ticks["value"]

    monkeypatch.setattr("plugins.builtin.retrieval_basic.plugin.time.perf_counter", _fake_perf_counter)
    stats: dict[str, object] = {}
    out = _scan_metadata_latest(
        _Store(),
        "nevermatches",
        None,
        limit=500,
        record_types=["derived.text.ocr"],
        budget_ms=50,
        stats=stats,
        stop_after=0,
    )
    assert out == []
    assert str(stats.get("latest_scan_reason") or "") == "LATEST_SCAN_BUDGET_EXCEEDED"
    assert int(stats.get("records_scanned", 0) or 0) < 500


def test_scan_metadata_latest_defaults_include_sst_extra_docs() -> None:
    class _Store:
        def latest(self, record_type: str | None, limit: int = 100):  # noqa: ARG002
            if record_type is None:
                return []
            if str(record_type) != "derived.sst.text.extra":
                return []
            return [
                {
                    "record_id": "run1/derived.sst.text.extra/1",
                    "record": {
                        "record_type": "derived.sst.text.extra",
                        "ts_utc": "2026-02-24T01:02:03Z",
                        "text": "Calendar panel month January 2026 and selected date February 2.",
                    },
                }
            ]

    out = _scan_metadata_latest(
        _Store(),
        "calendar month january 2026",
        None,
        limit=64,
        record_types=None,
        budget_ms=250,
        stats={},
        stop_after=0,
    )
    assert len(out) == 1
    assert str(out[0].get("record_type") or "") == "derived.sst.text.extra"


def test_retrieval_latest_scan_hard_cap_limits_candidates() -> None:
    calls: list[int] = []

    class _CapStore(_Store):
        def latest(self, record_type: str | None, limit: int = 100):  # type: ignore[override]
            calls.append(int(limit))
            return []

    store = _CapStore({})
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
                "latest_scan_limit": 2000,
                "latest_scan_hard_cap": 17,
                "attach_timelines": False,
            },
        }

        def _cap(name: str):
            if name == "storage.metadata":
                return store
            return None

        ctx = PluginContext(config=cfg, get_capability=_cap, logger=lambda _m, _p=None: None)
        retrieval = RetrievalStrategy("retrieval", ctx)
        _ = retrieval.search("anything", time_window=None)
        trace = retrieval.trace()
        latest_rows = [row for row in trace if str(row.get("tier") or "") == "LATEST_SCAN"]
        assert latest_rows
        assert int(latest_rows[0].get("limit", 0) or 0) == 17
        assert calls
        assert max(calls) <= 17
