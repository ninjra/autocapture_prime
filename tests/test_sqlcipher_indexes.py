import sqlite3
import tempfile
import unittest
from pathlib import Path

from plugins.builtin.storage_sqlcipher.plugin import SQLCipherStore


class SQLCipherIndexTests(unittest.TestCase):
    def test_metadata_indexes_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.db"
            store = SQLCipherStore(str(db_path), b"\x00" * 32, "run", "none")
            store._conn = sqlite3.connect(":memory:")
            store._init_schema()
            cur = store._conn.execute("PRAGMA index_list('metadata')")
            names = {row[1] for row in cur.fetchall()}
            self.assertIn("idx_metadata_record_type", names)
            self.assertIn("idx_metadata_ts_utc", names)
            self.assertIn("idx_metadata_run_id", names)


if __name__ == "__main__":
    unittest.main()
