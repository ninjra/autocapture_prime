import pytest


class _DictStore:
    def __init__(self):
        self._data = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def put(self, key, value):
        self._data[key] = value

    def put_new(self, key, value):
        if key in self._data:
            raise FileExistsError(key)
        self._data[key] = value

    def keys(self):
        return list(self._data.keys())


def test_schema_version_missing_normalized():
    from autocapture_nx.kernel.metadata_store import ImmutableMetadataStore

    raw = _DictStore()
    store = ImmutableMetadataStore(raw)
    record_id = "run_1/evidence.capture.frame/0"
    store.put_new(
        record_id,
        {
            "record_type": "evidence.capture.frame",
            "run_id": "run_1",
            "ts_utc": "2026-02-09T00:00:00Z",
            "content_hash": "deadbeef",
        },
    )
    stored = raw.get(record_id)
    assert stored["schema_version"] == 1
    assert isinstance(stored.get("payload_hash"), str) and stored["payload_hash"]


def test_schema_version_present_accepted():
    from autocapture_nx.kernel.metadata_store import ImmutableMetadataStore

    store = ImmutableMetadataStore(_DictStore())
    store.put_new(
        "run_1/evidence.capture.frame/0",
        {
            "schema_version": 1,
            "record_type": "evidence.capture.frame",
            "run_id": "run_1",
            "ts_utc": "2026-02-09T00:00:00Z",
            "content_hash": "deadbeef",
        },
    )


def test_payload_hash_recomputed_when_schema_version_injected():
    from autocapture_nx.kernel.hashing import sha256_canonical
    from autocapture_nx.kernel.metadata_store import ImmutableMetadataStore

    raw = _DictStore()
    store = ImmutableMetadataStore(raw)
    record_id = "run_1/derived.input.summary/0"
    payload = {
        "record_type": "derived.input.summary",
        "run_id": "run_1",
        "ts_utc": "2026-02-09T00:00:00Z",
        "start_ts_utc": "2026-02-09T00:00:00Z",
        "end_ts_utc": "2026-02-09T00:00:01Z",
        "event_id": "evt_1",
        "event_count": 1,
        "counts": {"key": 0, "mouse": 0},
        "mode": "win32_idle",
    }
    payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
    before = payload["payload_hash"]
    store.put_new(record_id, payload)
    stored = raw.get(record_id)
    assert stored["schema_version"] == 1
    assert stored["payload_hash"] != before
    expected = sha256_canonical({k: v for k, v in stored.items() if k != "payload_hash"})
    assert stored["payload_hash"] == expected
