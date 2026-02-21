from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path


def _load_module(path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, Path(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _init_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    try:
        con.execute(
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
        con.commit()
    finally:
        con.close()


def _put(path: Path, record_id: str, payload: dict[str, object]) -> None:
    con = sqlite3.connect(str(path))
    try:
        con.execute(
            "INSERT INTO metadata (id, record_type, ts_utc, payload, run_id) VALUES (?, ?, ?, ?, ?)",
            (
                record_id,
                str(payload.get("record_type") or ""),
                str(payload.get("ts_utc") or ""),
                json.dumps(payload, sort_keys=True),
                str(payload.get("run_id") or ""),
            ),
        )
        con.commit()
    finally:
        con.close()


def _count(path: Path, record_type: str) -> int:
    con = sqlite3.connect(str(path))
    try:
        row = con.execute("SELECT COUNT(*) FROM metadata WHERE record_type = ?", (record_type,)).fetchone()
        return int(row[0]) if row else 0
    finally:
        con.close()


def _snapshot(record_id: str, content_hash: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "evidence.uia.snapshot",
        "record_id": record_id,
        "run_id": "run1",
        "ts_utc": "2026-02-20T00:00:00Z",
        "unix_ms_utc": 1771603200000,
        "hwnd": "0x123",
        "window": {"title": "Inbox", "process_path": "C:\\Program Files\\Outlook.exe", "pid": 4242},
        "focus_path": [
            {
                "eid": "focus-1",
                "role": "Edit",
                "name": "Search",
                "aid": "SearchBox",
                "class": "Edit",
                "rect": [10, 10, 220, 40],
                "enabled": True,
                "offscreen": False,
            }
        ],
        "context_peers": [],
        "operables": [],
        "stats": {"walk_ms": 12, "nodes_emitted": 3, "failures": 0},
        "content_hash": content_hash,
    }


class BackfillUIAObsDocsMigrationTests(unittest.TestCase):
    def test_backfill_inserts_obs_uia_docs(self) -> None:
        mod = _load_module("tools/migrations/backfill_uia_obs_docs.py", "backfill_uia_obs_docs_1")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
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
                    "uia_ref": {"record_id": snapshot_id, "content_hash": "uia_hash_1"},
                },
            )
            _put(db_path, snapshot_id, _snapshot(snapshot_id, "uia_hash_1"))

            summary = mod.backfill_uia_obs_docs(db_path, dataroot=tmp, dry_run=False)

            self.assertEqual(int(summary.get("required_frames") or 0), 1)
            self.assertEqual(int(summary.get("ok_frames") or 0), 1)
            self.assertEqual(int(summary.get("missing_frames") or 0), 0)
            self.assertEqual(_count(db_path, "obs.uia.focus"), 1)
            self.assertEqual(_count(db_path, "obs.uia.context"), 1)
            self.assertEqual(_count(db_path, "obs.uia.operable"), 1)

    def test_backfill_dry_run_rolls_back(self) -> None:
        mod = _load_module("tools/migrations/backfill_uia_obs_docs.py", "backfill_uia_obs_docs_2")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            _init_db(db_path)
            frame_id = "run1/evidence.capture.frame/2"
            snapshot_id = "run1/evidence.uia.snapshot/2"
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
                    "uia_ref": {"record_id": snapshot_id, "content_hash": "uia_hash_2"},
                },
            )
            _put(db_path, snapshot_id, _snapshot(snapshot_id, "uia_hash_2"))

            summary = mod.backfill_uia_obs_docs(db_path, dataroot=tmp, dry_run=True)

            self.assertEqual(int(summary.get("required_frames") or 0), 1)
            self.assertEqual(_count(db_path, "obs.uia.focus"), 0)
            self.assertEqual(_count(db_path, "obs.uia.context"), 0)
            self.assertEqual(_count(db_path, "obs.uia.operable"), 0)

    def test_backfill_writes_to_derived_db_when_configured(self) -> None:
        mod = _load_module("tools/migrations/backfill_uia_obs_docs.py", "backfill_uia_obs_docs_derived")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            derived_db = Path(tmp) / "derived" / "stage1_derived.db"
            _init_db(db_path)
            frame_id = "run1/evidence.capture.frame/3"
            snapshot_id = "run1/evidence.uia.snapshot/3"
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
                    "uia_ref": {"record_id": snapshot_id, "content_hash": "uia_hash_3"},
                },
            )
            _put(db_path, snapshot_id, _snapshot(snapshot_id, "uia_hash_3"))

            summary = mod.backfill_uia_obs_docs(
                db_path,
                dataroot=tmp,
                derived_db_path=derived_db,
                dry_run=False,
            )

            self.assertEqual(int(summary.get("required_frames") or 0), 1)
            self.assertEqual(int(summary.get("ok_frames") or 0), 1)
            self.assertEqual(_count(db_path, "obs.uia.focus"), 0)
            self.assertEqual(_count(db_path, "obs.uia.context"), 0)
            self.assertEqual(_count(db_path, "obs.uia.operable"), 0)
            self.assertEqual(_count(derived_db, "obs.uia.focus"), 1)
            self.assertEqual(_count(derived_db, "obs.uia.context"), 1)
            self.assertEqual(_count(derived_db, "obs.uia.operable"), 1)

    def test_wait_for_db_stability_succeeds_for_static_file(self) -> None:
        mod = _load_module("tools/migrations/backfill_uia_obs_docs.py", "backfill_uia_obs_docs_wait_ok")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            db_path.write_bytes(b"seed")
            result = mod.wait_for_db_stability(
                db_path=db_path,
                stable_seconds=0.06,
                timeout_seconds=0.5,
                poll_interval_seconds=0.02,
            )
            self.assertTrue(bool(result.get("stable")))
            self.assertEqual(str(result.get("reason")), "stable")
            self.assertGreaterEqual(float(result.get("waited_seconds") or 0.0), 0.0)

    def test_wait_for_db_stability_times_out_for_churning_file(self) -> None:
        mod = _load_module("tools/migrations/backfill_uia_obs_docs.py", "backfill_uia_obs_docs_wait_timeout")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            db_path.write_bytes(b"seed")
            stop = threading.Event()

            def churn_file() -> None:
                i = 0
                while not stop.is_set():
                    i += 1
                    db_path.write_bytes(f"seed-{i}".encode("utf-8"))
                    time.sleep(0.01)

            t = threading.Thread(target=churn_file, daemon=True)
            t.start()
            try:
                result = mod.wait_for_db_stability(
                    db_path=db_path,
                    stable_seconds=0.10,
                    timeout_seconds=0.20,
                    poll_interval_seconds=0.02,
                )
            finally:
                stop.set()
                t.join(timeout=0.5)
            self.assertFalse(bool(result.get("stable")))
            self.assertEqual(str(result.get("reason")), "timeout")


if __name__ == "__main__":
    unittest.main()
