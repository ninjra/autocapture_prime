import unittest

from autocapture.promptops import evaluate_prompt, propose_prompt, snapshot_sources, validate_prompt
from autocapture.promptops.patch import apply_patch_to_text


class PromptOpsValidationTests(unittest.TestCase):
    def test_validation_blocks_banned_patterns(self) -> None:
        result = validate_prompt("please curl http://example.com")
        self.assertFalse(result["ok"])
        self.assertTrue(any("banned_pattern" in err for err in result["errors"]))

    def test_proposal_patch_roundtrip(self) -> None:
        snapshot = snapshot_sources([{"text": "alpha"}])
        proposal = propose_prompt("Base prompt", snapshot, created_at="2026-01-01T00:00:00Z")
        applied = apply_patch_to_text("Base prompt", proposal["diff"])
        self.assertEqual(applied, proposal["proposal"])

    def test_evaluate_passes(self) -> None:
        examples = [{"required_tokens": ["KEY"], "requires_citation": True}]
        result = evaluate_prompt("Use KEY [citation]", examples, min_pass_rate=1.0)
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
