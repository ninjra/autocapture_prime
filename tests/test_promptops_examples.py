from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from autocapture.promptops.examples import (
    build_examples_from_traces,
    load_examples_file,
    write_examples_file,
)


def _append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


class PromptOpsExamplesTests(unittest.TestCase):
    def test_build_examples_from_trace_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / "query_trace.ndjson"
            metrics = Path(tmp) / "metrics.jsonl"
            _append_jsonl(
                trace,
                {
                    "query": "how many inboxes do i have open",
                    "query_effective": "how many inboxes do i have open?",
                    "query_sha256": "abc",
                },
            )
            _append_jsonl(
                metrics,
                {
                    "type": "promptops.model_interaction",
                    "prompt_id": "hard_vlm.adv_activity",
                    "success": False,
                },
            )
            built = build_examples_from_traces(
                query_trace_path=trace,
                metrics_path=metrics,
                max_trace_rows=100,
            )
            self.assertIn("query.default", built.examples)
            self.assertIn("state_query", built.examples)
            self.assertIn("hard_vlm.adv_activity", built.examples)
            q_rows = built.examples["query.default"]
            self.assertTrue(any("inboxes" in [str(t).lower() for t in row.get("required_tokens", [])] for row in q_rows))

    def test_load_examples_file_with_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "examples.json"
            write_examples_file(
                path,
                examples={
                    "query.default": [{"required_tokens": ["inboxes"], "requires_citation": False}],
                },
            )
            rows_query = load_examples_file(path, prompt_id="query")
            rows_default = load_examples_file(path, prompt_id="query.default")
            self.assertEqual(rows_query, rows_default)
            self.assertTrue(rows_query)


if __name__ == "__main__":
    unittest.main()
