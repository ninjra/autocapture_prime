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


if __name__ == "__main__":
    unittest.main()
