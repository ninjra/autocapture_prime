import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autocapture_nx.kernel.activity_signal import is_activity_signal_fresh, load_activity_signal


class ActivitySignalReaderTests(unittest.TestCase):
    def test_reads_default_activity_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            activity_dir = root / "activity"
            activity_dir.mkdir(parents=True, exist_ok=True)
            signal_path = activity_dir / "activity_signal.json"
            signal_path.write_text(
                json.dumps(
                    {
                        "ts_utc": "2026-02-10T00:00:00+00:00",
                        "idle_seconds": 12.5,
                        "user_active": False,
                        "source": "sidecar",
                        "seq": 7,
                    }
                ),
                encoding="utf-8",
            )
            cfg = {"storage": {"data_dir": str(root)}}
            signal = load_activity_signal(cfg)
            self.assertIsNotNone(signal)
            assert signal is not None
            self.assertEqual(signal.ts_utc, "2026-02-10T00:00:00+00:00")
            self.assertAlmostEqual(signal.idle_seconds, 12.5)
            self.assertFalse(signal.user_active)
            self.assertEqual(signal.source, "sidecar")
            self.assertEqual(signal.seq, 7)

    def test_respects_explicit_signal_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            signal_path = root / "custom.json"
            signal_path.write_text(
                json.dumps(
                    {
                        "ts_utc": "2026-02-10T00:00:00+00:00",
                        "idle_seconds": 0,
                        "user_active": True,
                    }
                ),
                encoding="utf-8",
            )
            cfg = {
                "storage": {"data_dir": str(root)},
                "runtime": {"activity": {"sidecar_signal_path": str(signal_path)}},
            }
            signal = load_activity_signal(cfg)
            self.assertIsNotNone(signal)
            assert signal is not None
            self.assertTrue(signal.user_active)
            self.assertAlmostEqual(signal.idle_seconds, 0.0)

    def test_missing_or_invalid_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = {"storage": {"data_dir": str(root)}}
            self.assertIsNone(load_activity_signal(cfg))

            activity_dir = root / "activity"
            activity_dir.mkdir(parents=True, exist_ok=True)
            (activity_dir / "activity_signal.json").write_text("not json", encoding="utf-8")
            self.assertIsNone(load_activity_signal(cfg))

    def test_freshness_window_default_enforced(self) -> None:
        signal = type("S", (), {"ts_utc": datetime.now(timezone.utc).isoformat()})()
        cfg = {"runtime": {"activity": {}}}
        self.assertTrue(is_activity_signal_fresh(signal, cfg))
        stale = type("S", (), {"ts_utc": (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()})()
        self.assertFalse(is_activity_signal_fresh(stale, cfg))

    def test_freshness_window_respects_config_override(self) -> None:
        now = datetime.now(timezone.utc)
        signal = type("S", (), {"ts_utc": (now - timedelta(seconds=12)).isoformat()})()
        cfg = {"runtime": {"activity": {"max_signal_age_s": 20}}}
        self.assertTrue(is_activity_signal_fresh(signal, cfg, now_utc=now))


if __name__ == "__main__":
    unittest.main()
