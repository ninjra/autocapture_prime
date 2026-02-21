import sqlite3
import tempfile
import unittest
from pathlib import Path

from plugins.builtin.storage_sqlcipher.plugin import PlainSQLiteStore


class PlainSQLiteStoreRecoveryTests(unittest.TestCase):
    def test_archives_invalid_db_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "metadata.db"
            db_path.write_bytes(b"not-a-sqlite-file")

            store = PlainSQLiteStore(str(db_path), run_id="run_recovery", fsync_policy="none")
            self.assertEqual(store.keys(), [])

            self.assertTrue(db_path.exists(), "Expected store to recreate metadata.db")

            corrupt_dir = root / "corrupt"
            archived = list(corrupt_dir.glob("metadata.db.*.corrupt"))
            self.assertEqual(len(archived), 1, "Expected one archived corrupt DB copy")
            self.assertTrue((Path(str(archived[0]) + ".json")).exists(), "Expected recovery marker JSON")

            conn = sqlite3.connect(str(db_path))
            try:
                cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'")
                self.assertIsNotNone(cur.fetchone())
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
