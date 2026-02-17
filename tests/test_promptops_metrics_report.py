from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from tools import promptops_metrics_report as mod


class PromptOpsMetricsReportTests(unittest.TestCase):
    def test_build_report_aggregates_metrics(self) -> None:
        rows = [
            {
                "type": "promptops.prepare_prompt",
                "latency_ms": 10.0,
                "strategy": "normalize_query",
                "confidence": 0.8,
            },
            {
                "type": "promptops.prepare_prompt",
                "latency_ms": 30.0,
                "strategy": "normalize_query",
                "confidence": 0.6,
            },
            {
                "type": "promptops.model_interaction",
                "latency_ms": 100.0,
                "success": True,
            },
            {
                "type": "promptops.review_result",
                "updated": True,
                "pending_approval": False,
            },
        ]
        report = mod.build_report(rows)
        self.assertEqual(report["rows_total"], 4)
        self.assertEqual(report["prepare_prompt"]["count"], 2)
        self.assertGreater(report["prepare_prompt"]["latency_ms_p95"], 0.0)
        self.assertEqual(report["model_interaction"]["count"], 1)
        self.assertAlmostEqual(report["model_interaction"]["success_rate"], 1.0)
        self.assertEqual(report["review"]["updated_count"], 1)

    def test_main_writes_json_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            metrics = root / "metrics.jsonl"
            metrics.write_text(
                "\n".join(
                    [
                        json.dumps({"type": "promptops.prepare_prompt", "latency_ms": 12.0, "strategy": "none", "confidence": 0.5}),
                        json.dumps({"type": "promptops.model_interaction", "latency_ms": 80.0, "success": False}),
                    ]
                ),
                encoding="utf-8",
            )
            out_json = root / "out.json"
            out_csv = root / "out.csv"
            rc = mod.main(["--metrics", str(metrics), "--out-json", str(out_json), "--out-csv", str(out_csv)])
            self.assertEqual(rc, 0)
            self.assertTrue(out_json.exists())
            self.assertTrue(out_csv.exists())
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["rows_total"], 2)


if __name__ == "__main__":
    unittest.main()

