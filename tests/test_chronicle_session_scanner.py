from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from autocapture_prime.ingest.session_scanner import SessionScanner


class ChronicleSessionScannerTests(unittest.TestCase):
    def test_scanner_ignores_incomplete_and_tracks_processed(self) -> None:
        fixture_root = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "chronicle_spool"
        with tempfile.TemporaryDirectory() as td:
            state_db = Path(td) / "state.db"
            scanner = SessionScanner(fixture_root, state_db)
            complete = scanner.list_complete()
            ids = [item.session_id for item in complete]
            self.assertIn("test-0001", ids)
            self.assertNotIn("incomplete-0002", ids)

            pending = scanner.list_pending()
            self.assertEqual([item.session_id for item in pending], ["test-0001"])
            scanner.mark_processed(pending[0])
            pending_after = scanner.list_pending()
            self.assertEqual(pending_after, [])


if __name__ == "__main__":
    unittest.main()
