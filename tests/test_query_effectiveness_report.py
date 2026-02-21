from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import query_effectiveness_report


class QueryEffectivenessReportTests(unittest.TestCase):
    def test_builds_provider_and_sequence_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            facts = root / "facts"
            facts.mkdir(parents=True, exist_ok=True)
            traces = [
                {
                    "schema_version": 1,
                    "record_type": "derived.query.trace",
                    "ts_utc": "2026-02-11T00:00:00Z",
                    "query_run_id": "qry_1",
                    "query": "q1",
                    "method": "classic",
                    "winner": "classic",
                    "answer_state": "ok",
                    "answer_summary": "A1",
                    "coverage_bp": 10000,
                    "stage_ms": {"total": 120.0},
                    "handoffs": [{"from": "query", "to": "classic.query", "latency_ms": 80.0}],
                    "providers": [
                        {"provider_id": "builtin.observation.graph", "contribution_bp": 7000, "estimated_latency_ms": 60.0}
                    ],
                },
                {
                    "schema_version": 1,
                    "record_type": "derived.query.trace",
                    "ts_utc": "2026-02-11T00:01:00Z",
                    "query_run_id": "qry_2",
                    "query": "q2",
                    "method": "classic",
                    "winner": "classic",
                    "answer_state": "ok",
                    "answer_summary": "A2",
                    "coverage_bp": 9000,
                    "stage_ms": {"total": 180.0},
                    "handoffs": [{"from": "query", "to": "classic.query", "latency_ms": 140.0}],
                    "providers": [
                        {"provider_id": "builtin.observation.graph", "contribution_bp": 5000, "estimated_latency_ms": 90.0}
                    ],
                },
            ]
            feedback = [
                {
                    "schema_version": 2,
                    "record_type": "derived.eval.feedback",
                    "query_run_id": "qry_1",
                    "score_bp": 10000,
                    "verdict": "agree",
                },
                {
                    "schema_version": 2,
                    "record_type": "derived.eval.feedback",
                    "query_run_id": "qry_2",
                    "score_bp": 0,
                    "verdict": "disagree",
                },
            ]
            (facts / "query_trace.ndjson").write_text("\n".join(json.dumps(x) for x in traces) + "\n", encoding="utf-8")
            (facts / "query_feedback.ndjson").write_text("\n".join(json.dumps(x) for x in feedback) + "\n", encoding="utf-8")

            out_dir = root / "out"
            rc = query_effectiveness_report.main(
                [
                    "--data-dir",
                    str(root),
                    "--out-dir",
                    str(out_dir),
                    "--min-samples",
                    "1",
                    "--latency-threshold-ms",
                    "50",
                ]
            )
            self.assertEqual(rc, 0)
            report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
            self.assertTrue(report.get("ok"))
            self.assertEqual(report.get("summary", {}).get("runs_total"), 2)
            providers = report.get("provider_rows", [])
            self.assertEqual(len(providers), 1)
            self.assertEqual(providers[0].get("provider_id"), "builtin.observation.graph")
            self.assertEqual(providers[0].get("feedback_total"), 2)
            self.assertAlmostEqual(float(providers[0].get("accuracy", 0.0)), 0.5, places=3)
            rec_kinds = {str(item.get("kind") or "") for item in report.get("recommendations", []) if isinstance(item, dict)}
            self.assertIn("provider_low_accuracy_high_latency", rec_kinds)
            self.assertTrue((out_dir / "runs.csv").exists())
            self.assertTrue((out_dir / "providers.csv").exists())
            self.assertTrue((out_dir / "sequences.csv").exists())


if __name__ == "__main__":
    unittest.main()
