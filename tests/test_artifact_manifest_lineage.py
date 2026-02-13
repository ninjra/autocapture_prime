from __future__ import annotations


def test_artifact_manifest_record_is_valid_and_links_lineage():
    from autocapture_nx.kernel.metadata_store import ImmutableMetadataStore
    from autocapture_nx.kernel.derived_records import build_text_record, build_artifact_manifest, artifact_manifest_id

    class Store:
        def __init__(self):
            self._m = {}

        def get(self, k, default=None):
            return self._m.get(k, default)

        def put_new(self, k, v):
            if k in self._m:
                raise FileExistsError(k)
            self._m[k] = v

        def keys(self):
            return list(self._m.keys())

    meta = ImmutableMetadataStore(Store())
    evidence_id = "run_1/evidence.capture.frame/0"
    evidence = {
        "schema_version": 1,
        "record_type": "evidence.capture.frame",
        "run_id": "run_1",
        "ts_utc": "2026-02-09T00:00:00Z",
        "content_hash": "deadbeef",
    }
    meta.put_new(evidence_id, evidence)

    derived_id = "run_1/derived.text.ocr/stub/" + "src"
    payload = build_text_record(
        kind="ocr",
        text="hello",
        source_id=evidence_id,
        source_record={"run_id": "run_1", "ts_utc": "2026-02-09T00:00:00Z"},
        provider_id="stub",
        config={},
        ts_utc="2026-02-09T00:00:00Z",
    )
    assert payload is not None
    meta.put_new(derived_id, payload)

    manifest_id = artifact_manifest_id("run_1", derived_id)
    manifest = build_artifact_manifest(
        run_id="run_1",
        artifact_id=derived_id,
        artifact_sha256=str(payload.get("payload_hash") or payload.get("content_hash") or ""),
        derived_from={"evidence_id": evidence_id, "evidence_hash": evidence.get("content_hash")},
        ts_utc="2026-02-09T00:00:00Z",
    )
    meta.put_new(manifest_id, manifest)
    stored = meta.get(manifest_id)
    assert stored["record_type"] == "derived.artifact.manifest"
    assert stored["derived_from"]["evidence_id"] == evidence_id

