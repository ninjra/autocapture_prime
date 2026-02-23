from __future__ import annotations

import unittest
from unittest import mock

from autocapture_nx.kernel import query as query_mod


class _System:
    def __init__(self, *, query_enabled: bool = True) -> None:
        self.config = {
            "processing": {
                "query_pipeline_mode": "golden_state",
                "state_layer": {"query_enabled": bool(query_enabled)},
            }
        }


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
    def test_golden_state_mode_uses_single_state_path(self) -> None:
        system = _System()
        state_result = _result("State layer summary: coding session in progress.", coverage=1.0)
        with (
            mock.patch.object(query_mod, "run_state_query", return_value=state_result),
            mock.patch.object(query_mod, "run_query_without_state") as run_classic,
            mock.patch.object(query_mod, "_append_query_metric") as append_metric,
        ):
            out = query_mod.run_query(system, "summarize what i am working on")
        self.assertEqual(out.get("answer", {}).get("claims", [])[0].get("text"), state_result["answer"]["claims"][0]["text"])
        run_classic.assert_not_called()
        arb = out.get("processing", {}).get("arbitration", {})
        self.assertEqual(arb.get("winner"), "state")
        self.assertFalse(bool(arb.get("secondary_executed", True)))
        self.assertEqual(str(arb.get("mode") or ""), "single_golden_pipeline")
        golden = out.get("processing", {}).get("golden_pipeline", {})
        self.assertTrue(bool(golden.get("ok", False)))
        self.assertEqual(str(golden.get("mode") or ""), "single_golden_pipeline")
        append_metric.assert_called()
        self.assertEqual(append_metric.call_args.kwargs.get("method"), "state_golden")

    def test_golden_state_mode_returns_deterministic_error_when_state_disabled(self) -> None:
        system = _System(query_enabled=False)
        with (
            mock.patch.object(query_mod, "run_state_query") as run_state,
            mock.patch.object(query_mod, "run_query_without_state") as run_classic,
            mock.patch.object(query_mod, "_append_query_metric") as append_metric,
        ):
            out = query_mod.run_query(system, "summarize current work session")
        run_state.assert_not_called()
        run_classic.assert_not_called()
        answer = out.get("answer", {}) if isinstance(out.get("answer", {}), dict) else {}
        self.assertEqual(str(answer.get("state") or ""), "indeterminate")
        errors = answer.get("errors", []) if isinstance(answer.get("errors", []), list) else []
        first_error = errors[0] if errors and isinstance(errors[0], dict) else {}
        self.assertEqual(str(first_error.get("error") or ""), "golden_state_query_disabled")
        golden = out.get("processing", {}).get("golden_pipeline", {})
        self.assertFalse(bool(golden.get("ok", True)))
        self.assertEqual(str(golden.get("error_code") or ""), "golden_state_query_disabled")
        append_metric.assert_called()

    def test_golden_state_mode_returns_deterministic_error_on_state_exception(self) -> None:
        system = _System()
        with (
            mock.patch.object(query_mod, "run_state_query", side_effect=RuntimeError("boom")),
            mock.patch.object(query_mod, "run_query_without_state") as run_classic,
            mock.patch.object(query_mod, "_append_query_metric"),
        ):
            out = query_mod.run_query(system, "summarize current work session")
        run_classic.assert_not_called()
        answer = out.get("answer", {}) if isinstance(out.get("answer", {}), dict) else {}
        self.assertEqual(str(answer.get("state") or ""), "indeterminate")
        errors = answer.get("errors", []) if isinstance(answer.get("errors", []), list) else []
        first_error = errors[0] if errors and isinstance(errors[0], dict) else {}
        self.assertEqual(str(first_error.get("error") or ""), "golden_state_query_exception")
        golden = out.get("processing", {}).get("golden_pipeline", {})
        self.assertFalse(bool(golden.get("ok", True)))
        self.assertEqual(str(golden.get("error_code") or ""), "golden_state_query_exception")


if __name__ == "__main__":
    unittest.main()
