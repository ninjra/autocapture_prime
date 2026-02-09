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


def test_schema_version_missing_rejected():
    from autocapture_nx.kernel.metadata_store import ImmutableMetadataStore

    store = ImmutableMetadataStore(_DictStore())
    with pytest.raises(ValueError, match="missing schema_version"):
        store.put_new(
            "run_1/evidence.capture.frame/0",
            {
                "record_type": "evidence.capture.frame",
                "run_id": "run_1",
                "ts_utc": "2026-02-09T00:00:00Z",
                "content_hash": "deadbeef",
            },
        )


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

