from __future__ import annotations


def test_scan_metadata_order_is_deterministic() -> None:
    from plugins.builtin.retrieval_basic.plugin import _scan_metadata

    class Store:
        def __init__(self):
            self._records = {
                "b": {"schema_version": 1, "record_type": "derived.text.ocr", "run_id": "run_1", "ts_utc": "2026-02-09T00:00:02Z", "text": "hello world", "content_hash": "x"},
                "a": {"schema_version": 1, "record_type": "derived.text.ocr", "run_id": "run_1", "ts_utc": "2026-02-09T00:00:01Z", "text": "hello world", "content_hash": "y"},
            }
            self._flip = False

        def keys(self):
            # Return different orders across calls; retrieval must sort.
            self._flip = not self._flip
            return ["b", "a"] if self._flip else ["a", "b"]

        def get(self, key, default=None):
            return self._records.get(key, default)

    store = Store()
    r1 = _scan_metadata(store, "hello", None, None)
    r2 = _scan_metadata(store, "hello", None, None)
    assert [r["record_id"] for r in r1] == [r["record_id"] for r in r2] == ["a", "b"]

