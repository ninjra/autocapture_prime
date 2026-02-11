import tempfile
import unittest
from pathlib import Path

from autocapture_nx.state_layer.store_sqlite import StateTapeStore


class StateTapeStoreRecoveryTests(unittest.TestCase):
    def test_archives_invalid_db_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "state_tape.db"
            db_path.write_bytes(b"invalid-state-db")

            store = StateTapeStore(str(db_path), fsync_policy="none")
            marker = store.get_snapshot_marker()

            self.assertEqual(marker["span_count"], 0)
            self.assertTrue(db_path.exists(), "Expected state tape DB to be recreated")
            archived = list((root / "corrupt").glob("state_tape.db.*.corrupt"))
            self.assertEqual(len(archived), 1, "Expected one archived corrupt state DB copy")
            self.assertTrue((Path(str(archived[0]) + ".json")).exists(), "Expected recovery marker JSON")


if __name__ == "__main__":
    unittest.main()
