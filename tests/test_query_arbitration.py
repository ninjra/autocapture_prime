from __future__ import annotations

import unittest
from unittest import mock

from autocapture_nx.kernel import query as query_mod


class _System:
    def __init__(self) -> None:
        self.config = {"processing": {"state_layer": {"query_enabled": True}}}


def _result(claim_text: str, *, state: str = "ok", coverage: float = 0.0) -> dict:
    return {
        "answer": {
            "state": state,
            "claims": [{"text": claim_text, "citations": [{"evidence_id": "e1"}]}] if claim_text else [],
            "errors": [],
        },
        "evaluation": {"coverage_ratio": coverage},
        "results": [],
        "processing": {},
        "provenance": {},
    }


class QueryArbitrationTests(unittest.TestCase):
    def test_run_query_prefers_classic_when_more_grounded(self) -> None:
        system = _System()
        state_result = _result("@@@ noisy claim", coverage=0.0)
        classic_result = _result("Observation: open_inboxes_count=4. Open inboxes: 4", coverage=1.0)
        with (
            mock.patch.object(query_mod, "run_state_query", return_value=state_result),
            mock.patch.object(query_mod, "run_query_without_state", return_value=classic_result),
            mock.patch.object(query_mod, "_append_query_metric") as append_metric,
        ):
            out = query_mod.run_query(system, "how many inboxes do i have open")
        self.assertEqual(out.get("answer", {}).get("claims", [])[0].get("text"), classic_result["answer"]["claims"][0]["text"])
        arb = out.get("processing", {}).get("arbitration", {})
        self.assertEqual(arb.get("winner"), "classic")
        append_metric.assert_called()
        self.assertEqual(append_metric.call_args.kwargs.get("method"), "classic_arbitrated")

    def test_run_query_prefers_state_when_state_scores_higher(self) -> None:
        system = _System()
        state_result = _result("State layer summary: coding session in progress.", coverage=1.0)
        classic_result = _result("", state="no_evidence", coverage=0.0)
        with (
            mock.patch.object(query_mod, "run_state_query", return_value=state_result),
            mock.patch.object(query_mod, "run_query_without_state", return_value=classic_result),
            mock.patch.object(query_mod, "_append_query_metric") as append_metric,
        ):
            out = query_mod.run_query(system, "summarize what i am working on")
        self.assertEqual(out.get("answer", {}).get("claims", [])[0].get("text"), state_result["answer"]["claims"][0]["text"])
        arb = out.get("processing", {}).get("arbitration", {})
        self.assertEqual(arb.get("winner"), "state")
        append_metric.assert_called()
        self.assertEqual(append_metric.call_args.kwargs.get("method"), "state_arbitrated")

    def test_run_query_prefers_classic_for_background_color_signal(self) -> None:
        system = _System()
        state_result = _result("@@@ noisy background text with no color value", coverage=0.0)
        classic_result = _result("Observation: background_color=black; ui.background.primary_color=black.", coverage=1.0)
        with (
            mock.patch.object(query_mod, "run_state_query", return_value=state_result),
            mock.patch.object(query_mod, "run_query_without_state", return_value=classic_result),
            mock.patch.object(query_mod, "_append_query_metric") as append_metric,
        ):
            out = query_mod.run_query(system, "what color is the background")
        self.assertEqual(out.get("answer", {}).get("claims", [])[0].get("text"), classic_result["answer"]["claims"][0]["text"])
        arb = out.get("processing", {}).get("arbitration", {})
        self.assertEqual(arb.get("winner"), "classic")
        append_metric.assert_called()
        self.assertEqual(append_metric.call_args.kwargs.get("method"), "classic_arbitrated")


if __name__ == "__main__":
    unittest.main()
