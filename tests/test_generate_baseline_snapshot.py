from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.generate_baseline_snapshot import build_snapshot


class GenerateBaselineSnapshotTests(unittest.TestCase):
    def test_snapshot_hash_ignores_volatile_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sample = root / "sample.json"
            sample.write_text(
                json.dumps({"ok": True, "ts_utc": "2026-02-18T00:00:00Z", "duration_ms": 1.23456789}),
                encoding="utf-8",
            )
            first = build_snapshot([sample], root=root)
            sample.write_text(
                json.dumps({"ok": True, "ts_utc": "2026-02-18T00:00:01Z", "duration_ms": 1.23456780}),
                encoding="utf-8",
            )
            second = build_snapshot([sample], root=root)
            self.assertEqual(
                first.get("summary", {}).get("normalized_sha256"),
                second.get("summary", {}).get("normalized_sha256"),
            )

    def test_snapshot_tracks_missing_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            present = root / "present.json"
            missing = root / "missing.json"
            present.write_text(json.dumps({"ok": True}), encoding="utf-8")
            snap = build_snapshot([present, missing], root=root)
            self.assertEqual(int(snap.get("summary", {}).get("present_count", 0)), 1)
            self.assertEqual(int(snap.get("summary", {}).get("missing_count", 0)), 1)
            self.assertIn(str(missing), list(snap.get("missing", [])))


if __name__ == "__main__":
    unittest.main()
