from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock


def _load_module(path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, Path(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProcessingHealthSnapshotToolTests(unittest.TestCase):
    def test_resolve_manifests_path_explicit(self) -> None:
        mod = _load_module("tools/soak/processing_health_snapshot.py", "processing_health_snapshot_tool_1")
        out = mod.resolve_manifests_path("/tmp/custom.ndjson")
        self.assertEqual(str(out), "/tmp/custom.ndjson")

    def test_resolve_manifests_path_prefers_facts_default(self) -> None:
        mod = _load_module("tools/soak/processing_health_snapshot.py", "processing_health_snapshot_tool_2")
        preferred = "/mnt/d/autocapture/facts/landscape_manifests.ndjson"
        with mock.patch.object(Path, "exists", autospec=True) as exists:
            exists.side_effect = lambda p: str(p) == preferred
            out = mod.resolve_manifests_path("")
        self.assertEqual(str(out), preferred)

    def test_resolve_manifests_path_falls_back_legacy(self) -> None:
        mod = _load_module("tools/soak/processing_health_snapshot.py", "processing_health_snapshot_tool_3")
        legacy = "/mnt/d/autocapture/landscape_manifests.ndjson"
        with mock.patch.object(Path, "exists", autospec=True, return_value=False):
            out = mod.resolve_manifests_path("")
        self.assertEqual(str(out), legacy)

    def test_build_health_snapshot_raises_alerts(self) -> None:
        mod = _load_module("tools/soak/processing_health_snapshot.py", "processing_health_snapshot_tool_4")
        rows = [
            {
                "sla": {
                    "pending_records": 100,
                    "completed_records": 0,
                    "throughput_records_per_s": 0.0,
                    "projected_lag_hours": 12.0,
                    "retention_risk": True,
                },
                "metadata_db_guard": {"ok": False},
                "slo_alerts": ["throughput_zero_with_backlog"],
            }
        ]
        out = mod.build_health_snapshot(rows, tail=10)
        self.assertEqual(out["latest"]["pending_records"], 100)
        self.assertEqual(out["events"]["retention_risk"], 1)
        self.assertEqual(out["events"]["metadata_db_unstable"], 1)
        self.assertIn("retention_risk", out["alerts"])
        self.assertIn("metadata_db_unstable", out["alerts"])
        self.assertIn("throughput_zero_with_backlog", out["alerts"])


if __name__ == "__main__":
    unittest.main()
