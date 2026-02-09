from __future__ import annotations


def test_replay_dataset_writes_new_derived_records():
    from autocapture_nx.kernel.replay_dataset import replay_dataset

    class Meta:
        def __init__(self):
            self._m = {}

        def get(self, key, default=None):
            return self._m.get(key, default)

        def put_new(self, key, value):
            if key in self._m:
                raise FileExistsError(key)
            self._m[key] = value

        def put(self, key, value):
            self._m[key] = value

        def keys(self):
            return list(self._m.keys())

    class Media:
        def __init__(self, mapping):
            self._m = dict(mapping)

        def get(self, key, default=None):
            return self._m.get(key, default)

    class Extractor:
        def extract(self, _blob: bytes):
            return {"text": "deterministic ocr text"}

    class OCRPlugin:
        def capabilities(self):
            return {"ocr.engine": {"stub": Extractor()}}

    class System:
        def __init__(self, meta, media):
            self.config = {"models": {}, "promptops": {"enabled": False}}
            self._caps = {"storage.metadata": meta, "storage.media": media, "ocr.engine": OCRPlugin()}

        def get(self, name: str):
            return self._caps.get(name)

    meta = Meta()
    evidence_id = "run_src/evidence.capture.frame/0"
    meta.put_new(
        evidence_id,
        {
            "schema_version": 1,
            "record_type": "evidence.capture.frame",
            "run_id": "run_src",
            "ts_utc": "2026-02-09T00:00:00Z",
            "content_hash": "deadbeef",
        },
    )
    system = System(meta, Media({evidence_id: b"fake"}))
    report = replay_dataset(system, source_run_id="run_src", target_run_id="run_replay", limit=10)
    assert report.ok
    assert report.derived_written >= 1
    # Ensure at least one derived record is in the new run namespace.
    derived_ids = [k for k in meta.keys() if str(k).startswith("run_replay/derived.text.ocr/")]
    assert derived_ids

