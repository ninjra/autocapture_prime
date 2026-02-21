from __future__ import annotations

from pathlib import Path
import unittest

from autocapture_prime.ingest.session_loader import SessionLoader


class ChronicleSessionLoaderTests(unittest.TestCase):
    def test_loader_reads_manifest_meta_and_frames(self) -> None:
        session_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "chronicle_spool" / "session_test-0001"
        loader = SessionLoader(session_dir)
        loaded = loader.load()
        self.assertEqual(loaded.manifest.get("session_id"), "test-0001")
        self.assertEqual(len(loaded.frames_meta), 2)
        self.assertEqual(len(loaded.input_events), 1)
        frames = list(loader.iter_frames(loaded))
        self.assertEqual(len(frames), 2)
        self.assertTrue(frames[0][0].name.endswith(".png"))


if __name__ == "__main__":
    unittest.main()
