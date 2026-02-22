from __future__ import annotations

import importlib.util
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest


def _load_module():
    path = pathlib.Path("tools/repair_queryability_offline.py")
    spec = importlib.util.spec_from_file_location("repair_queryability_offline_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _init_db(path: pathlib.Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE metadata (
                id TEXT PRIMARY KEY,
                record_type TEXT,
                ts_utc TEXT,
                payload TEXT,
                run_id TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _put(path: pathlib.Path, record_id: str, payload: dict[str, object]) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "INSERT INTO metadata (id, record_type, ts_utc, payload, run_id) VALUES (?, ?, ?, ?, ?)",
            (
                record_id,
                str(payload.get("record_type") or ""),
                str(payload.get("ts_utc") or ""),
                json.dumps(payload, sort_keys=True),
                str(payload.get("run_id") or ""),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _count(path: pathlib.Path, record_type: str) -> int:
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute("SELECT COUNT(*) FROM metadata WHERE record_type = ?", (record_type,)).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def _snapshot(record_id: str, content_hash: str) -> dict[str, object]:
    node_focus = {
        "eid": "focus-1",
        "role": "Edit",
        "name": "Search",
        "aid": "SearchBox",
        "class": "Edit",
        "rect": [10, 10, 220, 40],
        "enabled": True,
        "offscreen": False,
    }
    node_context = {
        "eid": "ctx-1",
        "role": "ListItem",
        "name": "Inbox",
        "aid": "InboxRow",
        "class": "ListViewItem",
        "rect": [10, 50, 220, 80],
        "enabled": True,
        "offscreen": False,
    }
    node_operable = {
        "eid": "op-1",
        "role": "Button",
        "name": "Send",
        "aid": "SendButton",
        "class": "Button",
        "rect": [230, 10, 300, 40],
        "enabled": True,
        "offscreen": False,
    }
    return {
        "schema_version": 1,
        "record_type": "evidence.uia.snapshot",
        "record_id": record_id,
        "run_id": "run1",
        "ts_utc": "2026-02-20T00:00:00Z",
        "unix_ms_utc": 1771603200000,
        "hwnd": "0x123",
        "window": {"title": "Inbox", "process_path": "C:\\Program Files\\Outlook.exe", "pid": 4242},
        "focus_path": [node_focus],
        "context_peers": [node_context],
        "operables": [node_operable],
        "stats": {"walk_ms": 12, "nodes_emitted": 3, "failures": 0},
        "content_hash": content_hash,
    }


class RepairQueryabilityOfflineTests(unittest.TestCase):
    def test_repair_backfills_uia_stage1_retention_and_is_idempotent(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            db_path = root / "metadata.db"
            derived_db = root / "derived" / "stage1_derived.db"
            out1 = root / "repair1.json"
            out2 = root / "repair2.json"
            _init_db(db_path)

            frame_id = "run1/evidence.capture.frame/1"
            snapshot_id = "run1/evidence.uia.snapshot/1"
            _put(
                db_path,
                frame_id,
                {
                    "schema_version": 1,
                    "record_type": "evidence.capture.frame",
                    "run_id": "run1",
                    "ts_utc": "2026-02-20T00:00:00Z",
                    "width": 320,
                    "height": 180,
                    "blob_path": "captures/f1.png",
                    "content_hash": "frame_hash_1",
                    "uia_ref": {"record_id": snapshot_id, "content_hash": "uia_hash_1"},
                    "input_ref": {"record_id": "run1/evidence.input.batch/1"},
                },
            )
            _put(db_path, snapshot_id, _snapshot(snapshot_id, "uia_hash_1"))

            rc1 = mod.main(
                [
                    "--db",
                    str(db_path),
                    "--derived-db",
                    str(derived_db),
                    "--dataroot",
                    str(root),
                    "--out",
                    str(out1),
                ]
            )
            self.assertEqual(rc1, 0)
            payload1 = json.loads(out1.read_text(encoding="utf-8"))
            self.assertTrue(bool(payload1.get("ok", False)))
            self.assertEqual(int(payload1.get("post_audit", {}).get("summary", {}).get("frames_queryable", 0) or 0), 1)
            self.assertEqual(_count(derived_db, "obs.uia.focus"), 1)
            self.assertEqual(_count(derived_db, "obs.uia.context"), 1)
            self.assertEqual(_count(derived_db, "obs.uia.operable"), 1)
            self.assertEqual(_count(derived_db, "derived.ingest.stage1.complete"), 1)
            self.assertEqual(_count(derived_db, "retention.eligible"), 1)

            rc2 = mod.main(
                [
                    "--db",
                    str(db_path),
                    "--derived-db",
                    str(derived_db),
                    "--dataroot",
                    str(root),
                    "--out",
                    str(out2),
                ]
            )
            self.assertEqual(rc2, 0)
            payload2 = json.loads(out2.read_text(encoding="utf-8"))
            self.assertEqual(int(payload2.get("backfill_stage1_retention", {}).get("stage1_inserted", -1)), 0)
            self.assertEqual(int(payload2.get("backfill_stage1_retention", {}).get("retention_inserted", -1)), 0)
            self.assertEqual(_count(derived_db, "obs.uia.focus"), 1)
            self.assertEqual(_count(derived_db, "derived.ingest.stage1.complete"), 1)
            self.assertEqual(_count(derived_db, "retention.eligible"), 1)

    def test_repair_enforces_min_queryable_ratio(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            db_path = root / "metadata.db"
            out = root / "repair.json"
            _init_db(db_path)
            _put(
                db_path,
                "run1/evidence.capture.frame/2",
                {
                    "schema_version": 1,
                    "record_type": "evidence.capture.frame",
                    "run_id": "run1",
                    "ts_utc": "2026-02-20T00:00:00Z",
                    "width": 320,
                    "height": 180,
                    "blob_path": "captures/f2.png",
                    "content_hash": "frame_hash_2",
                    # No uia_ref/input_ref -> cannot become stage1/queryability complete.
                },
            )
            rc = mod.main(
                [
                    "--db",
                    str(db_path),
                    "--dataroot",
                    str(root),
                    "--min-queryable-ratio",
                    "1.0",
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            reasons = set(payload.get("failure_reasons", []))
            self.assertIn("queryable_ratio_below_threshold", reasons)


if __name__ == "__main__":
    unittest.main()
