from __future__ import annotations

from typing import Any

from autocapture_nx.ingest.stage2_projection_docs import project_stage2_docs_for_frame


class _Store:
    def __init__(self, data: dict[str, dict[str, Any]] | None = None) -> None:
        self.data = dict(data or {})

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def put_new(self, key: str, value: dict[str, Any]) -> None:
        if key in self.data:
            raise FileExistsError(key)
        self.data[key] = dict(value)

    def put(self, key: str, value: dict[str, Any]) -> None:
        self.data[key] = dict(value)


def _snapshot_payload(record_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "evidence.uia.snapshot",
        "record_id": record_id,
        "run_id": "run_test",
        "ts_utc": "2026-02-20T00:00:00Z",
        "unix_ms_utc": 1771603200000,
        "hwnd": "0x123",
        "window": {"title": "Remote Desktop Web Client", "process_path": "C:\\Program Files\\Chrome\\chrome.exe", "pid": 4242},
        "focus_path": [
            {
                "eid": "focus-1",
                "role": "Text",
                "name": "NCAAW game starts 8:00 PM",
                "aid": "focus",
                "class": "TextBlock",
                "rect": [10, 10, 300, 40],
                "enabled": True,
                "offscreen": False,
            }
        ],
        "context_peers": [],
        "operables": [],
        "stats": {"walk_ms": 12, "nodes_emitted": 3, "failures": 0},
        "content_hash": "uia_hash_1",
    }


def test_stage2_projection_docs_deterministic_and_idempotent() -> None:
    frame_id = "run_test/evidence.capture.frame/1"
    uia_id = "run_test/evidence.uia.snapshot/1"
    store = _Store(
        {
            frame_id: {
                "record_type": "evidence.capture.frame",
                "run_id": "run_test",
                "ts_utc": "2026-02-20T00:00:00Z",
                "uia_ref": {"record_id": uia_id, "content_hash": "uia_hash_1"},
                "width": 1920,
                "height": 1080,
            },
            uia_id: _snapshot_payload(uia_id),
        }
    )
    frame = dict(store.get(frame_id, {}))

    first = project_stage2_docs_for_frame(store, source_record_id=frame_id, frame_record=frame, read_store=store, dry_run=False)
    assert bool(first.get("ok", False))
    assert int(first.get("generated_docs", 0) or 0) >= 1
    assert int(first.get("inserted_docs", 0) or 0) >= 1
    first_ids = sorted([rid for rid, row in store.data.items() if str(row.get("record_type") or "") == "derived.sst.text.extra"])
    assert len(first_ids) >= 1

    second = project_stage2_docs_for_frame(store, source_record_id=frame_id, frame_record=frame, read_store=store, dry_run=False)
    assert bool(second.get("ok", False))
    second_ids = sorted([rid for rid, row in store.data.items() if str(row.get("record_type") or "") == "derived.sst.text.extra"])
    assert second_ids == first_ids


def test_stage2_projection_docs_missing_uia_ref_is_safe_noop() -> None:
    frame_id = "run_test/evidence.capture.frame/2"
    store = _Store(
        {
            frame_id: {
                "record_type": "evidence.capture.frame",
                "run_id": "run_test",
                "ts_utc": "2026-02-20T00:00:00Z",
                "width": 1920,
                "height": 1080,
            }
        }
    )
    frame = dict(store.get(frame_id, {}))
    result = project_stage2_docs_for_frame(store, source_record_id=frame_id, frame_record=frame, read_store=store, dry_run=False)
    assert bool(result.get("ok", False))
    assert int(result.get("inserted_docs", 0) or 0) == 0
    assert int(result.get("errors", 0) or 0) == 0
