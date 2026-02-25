from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load_module():
    path = Path("tools/gate_memory_soak.py")
    spec = importlib.util.spec_from_file_location("gate_memory_soak_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GateMemorySoakTests(unittest.TestCase):
    def test_evaluate_memory_soak_passes(self) -> None:
        mod = _load_module()
        ok, reasons, observed = mod.evaluate_memory_soak(
            {
                "loops": 300,
                "rss_delta_mb": 0.25,
                "rss_tail_span_mb": 0.0,
                "promptops_layers_last": 1,
                "promptops_apis_last": 1,
                "query_fast_cache_last": 0,
                "lat_p95_ms": 900.0,
            },
            min_loops=200,
            max_rss_delta_mb=8.0,
            max_rss_tail_span_mb=2.0,
            max_promptops_service_cache_entries=16,
            max_query_fast_cache_entries=4096,
            max_p95_ms=2500.0,
        )
        self.assertTrue(ok)
        self.assertEqual(reasons, [])
        self.assertEqual(observed["loops"], 300)

    def test_evaluate_memory_soak_fails_with_reasons(self) -> None:
        mod = _load_module()
        ok, reasons, _observed = mod.evaluate_memory_soak(
            {
                "loops": 10,
                "rss_delta_mb": 42.0,
                "rss_tail_span_mb": 6.0,
                "promptops_layers_last": 20,
                "promptops_apis_last": 20,
                "query_fast_cache_last": 5000,
                "lat_p95_ms": 5000.0,
            },
            min_loops=200,
            max_rss_delta_mb=8.0,
            max_rss_tail_span_mb=2.0,
            max_promptops_service_cache_entries=16,
            max_query_fast_cache_entries=4096,
            max_p95_ms=2500.0,
        )
        self.assertFalse(ok)
        self.assertIn("loops_below_min", reasons)
        self.assertIn("rss_delta_exceeds_limit", reasons)
        self.assertIn("rss_tail_span_exceeds_limit", reasons)
        self.assertIn("promptops_layers_exceeds_limit", reasons)
        self.assertIn("promptops_apis_exceeds_limit", reasons)
        self.assertIn("query_fast_cache_exceeds_limit", reasons)
        self.assertIn("latency_p95_exceeds_limit", reasons)

    def test_main_emits_missing_summary(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "gate.json"
            rc = mod.main(["--summary", str(Path(tmp) / "missing.json"), "--out", str(out)])
            self.assertEqual(rc, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["reasons"], ["summary_missing"])

    def test_main_writes_passing_report(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary.json"
            out = Path(tmp) / "gate.json"
            summary.write_text(
                json.dumps(
                    {
                        "loops": 300,
                        "rss_delta_mb": 0.25,
                        "rss_tail_span_mb": 0.0,
                        "promptops_layers_last": 1,
                        "promptops_apis_last": 1,
                        "query_fast_cache_last": 0,
                        "lat_p95_ms": 900.0,
                    }
                ),
                encoding="utf-8",
            )
            rc = mod.main(["--summary", str(summary), "--out", str(out)])
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["reasons"], [])

    def test_main_accepts_nested_summary_shape(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary.json"
            out = Path(tmp) / "gate.json"
            summary.write_text(
                json.dumps(
                    {
                        "summary": {
                            "loops": 300,
                            "rss_delta_mb": 0.25,
                            "rss_tail_span_mb": 0.0,
                            "promptops_layers_last": 1,
                            "promptops_apis_last": 1,
                            "query_fast_cache_last": 0,
                            "lat_p95_ms": 900.0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            rc = mod.main(["--summary", str(summary), "--out", str(out)])
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
