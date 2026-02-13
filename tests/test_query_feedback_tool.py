from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from tools import query_feedback


class QueryFeedbackToolTests(unittest.TestCase):
    def test_feedback_uses_latest_trace_when_query_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            try:
                facts = Path(tmp) / "facts"
                facts.mkdir(parents=True, exist_ok=True)
                trace_payload = {
                    "schema_version": 1,
                    "record_type": "derived.query.trace",
                    "query_run_id": "qry_abc123",
                    "query": "how many inboxes do i have open",
                    "query_sha256": "hash",
                }
                (facts / "query_trace.ndjson").write_text(json.dumps(trace_payload) + "\n", encoding="utf-8")

                rc = query_feedback.main(
                    [
                        "--verdict",
                        "agree",
                        "--notes",
                        "looks right",
                        "--plugin-id",
                        "builtin.observation.graph",
                    ]
                )
                self.assertEqual(rc, 0)
                out_path = facts / "query_feedback.ndjson"
                self.assertTrue(out_path.exists())
                rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row.get("query_run_id"), "qry_abc123")
                self.assertEqual(row.get("query"), "how many inboxes do i have open")
                self.assertEqual(int(row.get("score_bp", 0)), 10000)
                self.assertEqual(row.get("verdict"), "agree")
                self.assertEqual(row.get("plugin_ids"), ["builtin.observation.graph"])
            finally:
                if original_data is None:
                    os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_DATA_DIR"] = original_data


if __name__ == "__main__":
    unittest.main()
