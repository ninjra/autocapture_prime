from __future__ import annotations


def test_retrieval_sort_key_is_deterministic() -> None:
    # Mirrors plugins/builtin/retrieval_basic/plugin.py sorting contract.
    # We keep this test local and deterministic (no plugin boot).
    results = [
        {"record_id": "b", "derived_id": None, "record_type": "evidence.capture.frame", "ts_utc": "2026-02-02T00:00:02+00:00", "score": 1.0},
        {"record_id": "a", "derived_id": None, "record_type": "evidence.capture.frame", "ts_utc": "2026-02-02T00:00:02+00:00", "score": 1.0},
        {"record_id": "a", "derived_id": "d1", "record_type": "evidence.capture.frame", "ts_utc": "2026-02-02T00:00:03+00:00", "score": 1.0},
        {"record_id": "a", "derived_id": "d0", "record_type": "evidence.capture.frame", "ts_utc": "2026-02-02T00:00:03+00:00", "score": 1.0},
        {"record_id": "z", "derived_id": None, "record_type": "evidence.capture.frame", "ts_utc": None, "score": 0.5},
    ]

    from plugins.builtin.retrieval_basic.plugin import _ts_key

    results.sort(
        key=lambda r: (
            -float(r.get("score", 0.0)),
            -(_ts_key(r.get("ts_utc")) or 0.0),
            str(r.get("record_type", "")),
            str(r.get("record_id", "")),
            str(r.get("derived_id", "")),
        )
    )

    # Highest score; latest timestamp first; then stable by record_id then derived_id.
    assert [r.get("record_id") for r in results[:4]] == ["a", "a", "a", "b"]
    assert [r.get("derived_id") for r in results[:3]] == ["d0", "d1", None]
    assert results[-1]["record_id"] == "z"

