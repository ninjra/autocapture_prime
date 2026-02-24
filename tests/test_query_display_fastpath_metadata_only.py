from __future__ import annotations

import os
import unittest
from unittest import mock

from autocapture_nx.kernel import query as query_mod


class QueryDisplayFastpathMetadataOnlyTests(unittest.TestCase):
    def test_no_claim_sources_skips_fallback_scan_in_metadata_only_mode(self) -> None:
        with (
            mock.patch.dict(os.environ, {"AUTOCAPTURE_QUERY_METADATA_ONLY": "1"}, clear=False),
            mock.patch.object(
                query_mod,
                "_augment_claim_sources_for_display",
                side_effect=AssertionError("fallback_scan_should_not_run"),
            ),
        ):
            display = query_mod._build_answer_display(
                "what am i working on right now",
                [],
                [],
                metadata=object(),
                query_intent={"topic": "song"},
            )
        self.assertEqual(str(display.get("topic") or ""), "song")
        self.assertIn("Indeterminate", str(display.get("summary") or ""))

    def test_apply_answer_display_skips_fallback_scan_with_no_claims(self) -> None:
        class _System:
            config = {}

            def get(self, _name: str):  # noqa: ANN001
                return None

        result = {"answer": {"state": "no_evidence", "claims": []}, "processing": {}}
        with (
            mock.patch.dict(os.environ, {"AUTOCAPTURE_QUERY_METADATA_ONLY": "1"}, clear=False),
            mock.patch.object(
                query_mod,
                "_augment_claim_sources_for_display",
                side_effect=AssertionError("fallback_scan_should_not_run"),
            ),
        ):
            out = query_mod._apply_answer_display(
                _System(),
                "what am i working on right now",
                result,
                query_intent={"topic": "song"},
            )
        answer = out.get("answer", {}) if isinstance(out.get("answer", {}), dict) else {}
        self.assertEqual(str(answer.get("state") or ""), "no_evidence")
        display = answer.get("display", {}) if isinstance(answer.get("display", {}), dict) else {}
        self.assertEqual(str(display.get("topic") or ""), "song")
        self.assertIn("Indeterminate", str(display.get("summary") or ""))

    def test_advanced_topic_does_not_skip_fallback_scan_in_metadata_only_mode(self) -> None:
        with (
            mock.patch.dict(os.environ, {"AUTOCAPTURE_QUERY_METADATA_ONLY": "1"}, clear=False),
            mock.patch.object(
                query_mod,
                "_augment_claim_sources_for_display",
                return_value=[
                    {
                        "provider_id": "builtin.processing.sst.pipeline",
                        "doc_kind": "adv.window.inventory",
                        "signal_pairs": {
                            "adv.window.count": "2",
                            "adv.window.1.app": "Outlook VDI",
                            "adv.window.1.context": "vdi",
                            "adv.window.1.visibility": "partially_occluded",
                            "adv.window.2.app": "Slack",
                            "adv.window.2.context": "host",
                            "adv.window.2.visibility": "partially_occluded",
                        },
                        "meta": {},
                    }
                ],
            ) as augment_mock,
        ):
            display = query_mod._build_answer_display(
                "Enumerate top-level windows",
                [],
                [],
                metadata=object(),
                query_intent={"topic": "adv_window_inventory"},
            )
        self.assertGreaterEqual(int(augment_mock.call_count), 1)
        self.assertIn("Visible top-level windows", str(display.get("summary") or ""))


if __name__ == "__main__":
    unittest.main()
