from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autocapture_nx.kernel.sqlite_reads import open_sqlite_reader


class SqliteReadsSnapshotTests(unittest.TestCase):
    def _seed_db(self, path: Path) -> None:
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("CREATE TABLE metadata (id TEXT PRIMARY KEY, record_type TEXT, payload TEXT)")
            conn.execute("INSERT INTO metadata (id, record_type, payload) VALUES (?, ?, ?)", ("row1", "demo", "{}"))
            conn.commit()
        finally:
            conn.close()

    def test_force_snapshot_reader_opens_and_queries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "metadata.db"
            self._seed_db(db_path)
            conn, info = open_sqlite_reader(db_path, prefer_snapshot=True, force_snapshot=True)
            try:
                row = conn.execute("SELECT COUNT(*) AS n FROM metadata").fetchone()
            finally:
                conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(int(row["n"] or 0), 1)
            self.assertEqual(str(info.get("mode") or ""), "snapshot")

    def test_direct_reader_falls_back_to_snapshot_on_transient_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "metadata.db"
            self._seed_db(db_path)
            real_connect = sqlite3.connect

            def _patched_connect(*args, **kwargs):  # noqa: ANN002,ANN003
                uri = bool(kwargs.get("uri", False))
                target = str(args[0]) if args else ""
                if uri and "immutable=1" in target and str(db_path) in target:
                    raise sqlite3.OperationalError("disk I/O error")
                return real_connect(*args, **kwargs)

            with mock.patch("autocapture_nx.kernel.sqlite_reads.sqlite3.connect", side_effect=_patched_connect):
                conn, info = open_sqlite_reader(db_path, prefer_snapshot=True, force_snapshot=False)
                try:
                    row = conn.execute("SELECT COUNT(*) AS n FROM metadata").fetchone()
                finally:
                    conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(int(row["n"] or 0), 1)
            self.assertEqual(str(info.get("mode") or ""), "snapshot_fallback")


if __name__ == "__main__":
    unittest.main()
