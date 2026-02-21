from __future__ import annotations

import unittest

from autocapture_nx.kernel import query as query_mod


class QuerySourceClassGuardTests(unittest.TestCase):
    def test_allows_capture_and_core_derived_sources(self) -> None:
        self.assertTrue(query_mod._is_allowed_claim_record_type("evidence.capture.frame"))
        self.assertTrue(query_mod._is_allowed_claim_record_type("obs.uia.focus"))
        self.assertTrue(query_mod._is_allowed_claim_record_type("obs.uia.context"))
        self.assertTrue(query_mod._is_allowed_claim_record_type("obs.uia.operable"))
        self.assertTrue(query_mod._is_allowed_claim_record_type("derived.text.ocr"))
        self.assertTrue(query_mod._is_allowed_claim_record_type("derived.state.answer"))
        self.assertTrue(query_mod._is_allowed_claim_record_type("derived.obs.entity"))

    def test_blocks_eval_and_query_record_types(self) -> None:
        self.assertFalse(query_mod._is_allowed_claim_record_type("evidence.uia.snapshot"))
        self.assertFalse(query_mod._is_allowed_claim_record_type("derived.eval.feedback"))
        self.assertFalse(query_mod._is_allowed_claim_record_type("derived.query.trace"))
        self.assertFalse(query_mod._is_allowed_claim_record_type("derived.job.extract"))


if __name__ == "__main__":
    unittest.main()
