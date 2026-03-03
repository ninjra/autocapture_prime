from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autocapture_nx.storage.stage1_derived_store import (
    Stage1DerivedSqliteStore,
    Stage1OverlayStore,
    default_stage1_derived_db_path,
    resolve_stage1_derived_db_path,
)


class _ReadStore:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, object]] = {}

    def put(self, record_id: str, value: dict[str, object]) -> None:
        self._rows[str(record_id)] = dict(value)

    def get(self, record_id: str, default=None):  # noqa: ANN001
        return self._rows.get(str(record_id), default)


class _FaultyReadStore(_ReadStore):
    def get(self, record_id: str, default=None):  # noqa: ANN001
        raise OSError("disk I/O error")


class Stage1DerivedStoreTests(unittest.TestCase):
    def test_default_path_under_dataroot(self) -> None:
        out = default_stage1_derived_db_path("/tmp/ac")
        self.assertEqual(str(out), "/tmp/ac/derived/stage1_derived.db")

    def test_resolve_disabled_returns_none(self) -> None:
        cfg = {"storage": {"stage1_derived": {"enabled": False}}}
        self.assertIsNone(resolve_stage1_derived_db_path(cfg))

    def test_resolve_enabled_uses_explicit_path(self) -> None:
        cfg = {"storage": {"stage1_derived": {"enabled": True, "db_path": "/tmp/custom.db"}}}
        out = resolve_stage1_derived_db_path(cfg)
        self.assertEqual(str(out), "/tmp/custom.db")

    def test_resolve_auto_detects_existing_db_when_flag_absent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            derived = Path(td) / "derived" / "stage1_derived.db"
            derived.parent.mkdir(parents=True, exist_ok=True)
            derived.touch()
            cfg = {"storage": {"data_dir": td}}
            out = resolve_stage1_derived_db_path(cfg)
            self.assertEqual(str(out), str(derived))

    def test_resolve_auto_detect_returns_none_when_db_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = {"storage": {"data_dir": td}}
            out = resolve_stage1_derived_db_path(cfg)
            self.assertIsNone(out)

    def test_overlay_reads_derived_first_and_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "derived.db"
            derived = Stage1DerivedSqliteStore(db_path)
            read = _ReadStore()
            read.put("x", {"record_type": "evidence.capture.frame", "v": 1})
            overlay = Stage1OverlayStore(metadata_read=read, derived_write=derived)
            overlay.put_new("d1", {"record_type": "derived.ingest.stage1.complete", "v": 2})
            self.assertEqual((overlay.get("d1") or {}).get("v"), 2)
            self.assertEqual((overlay.get("x") or {}).get("v"), 1)

    def test_overlay_fail_open_when_metadata_read_get_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "derived.db"
            derived = Stage1DerivedSqliteStore(db_path)
            overlay = Stage1OverlayStore(metadata_read=_FaultyReadStore(), derived_write=derived)
            self.assertIsNone(overlay.get("missing"))

    def test_stage2_marker_idempotent_put(self) -> None:
        """Stage2 completion markers should use put() (upsert) for idempotent re-runs."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "derived.db"
            derived = Stage1DerivedSqliteStore(db_path)
            marker = {
                "record_type": "derived.ingest.stage2.complete",
                "source_record_id": "frame/123",
                "complete": True,
                "ts_utc": "2026-02-28T12:00:00Z",
            }
            # First write
            derived.put("stage2/frame/123", marker)
            self.assertEqual((derived.get("stage2/frame/123") or {}).get("complete"), True)
            # Second write (idempotent) — should not raise
            marker_updated = dict(marker)
            marker_updated["ts_utc"] = "2026-02-28T13:00:00Z"
            derived.put("stage2/frame/123", marker_updated)
            self.assertEqual(
                (derived.get("stage2/frame/123") or {}).get("ts_utc"),
                "2026-02-28T13:00:00Z",
            )
            self.assertEqual(derived.count(record_type="derived.ingest.stage2.complete"), 1)

    def test_overlay_put_uses_derived_write(self) -> None:
        """Overlay store puts should go to derived, not to metadata_read."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "derived.db"
            derived = Stage1DerivedSqliteStore(db_path)
            read = _ReadStore()
            overlay = Stage1OverlayStore(metadata_read=read, derived_write=derived)
            marker = {
                "record_type": "derived.ingest.stage2.complete",
                "complete": True,
            }
            overlay.put("stage2/frame/abc", marker)
            # Must be in derived
            self.assertIsNotNone(derived.get("stage2/frame/abc"))
            # Must be readable through overlay
            self.assertEqual((overlay.get("stage2/frame/abc") or {}).get("complete"), True)


if __name__ == "__main__":
    unittest.main()
