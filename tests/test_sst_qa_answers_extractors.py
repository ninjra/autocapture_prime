import unittest


class SSTQAAnswersExtractorsTests(unittest.TestCase):
    def test_count_inboxes_counts_multiword_tokens(self) -> None:
        from plugins.builtin.sst_qa_answers import plugin as qa

        tokens = [
            {"text": "M Inbox", "bbox": [100, 10, 160, 30]},
            {"text": "M Inbox", "bbox": [400, 10, 460, 30]},
            {"text": "Inbox", "bbox": [900, 200, 940, 240]},
            # Noise that should not count.
            {"text": "Inboxes", "bbox": [900, 260, 980, 300]},
            {"text": "Inboxing", "bbox": [10, 500, 90, 520]},
        ]
        # Multi-word "M Inbox" tokens on the same top-bar y-band should dedupe.
        self.assertEqual(qa._count_inboxes(tokens), 2)

    def test_extract_quorum_collaborator_prefers_assignee_token(self) -> None:
        from plugins.builtin.sst_qa_answers import plugin as qa

        tokens = [
            # Decoy capitalized words near Quorum.
            {"text": "Quorum", "bbox": [10, 10, 60, 30]},
            {"text": "Yesterday", "bbox": [80, 10, 160, 30]},
            {"text": "Priority", "bbox": [170, 10, 240, 30]},
            # The assignee token we want.
            {"text": "taskwasassignedtoOpenInvoice", "bbox": [10, 120, 320, 140]},
        ]
        collaborator, bbox = qa._extract_quorum_collaborator(tokens)
        self.assertEqual(collaborator, "Open Invoice")
        self.assertEqual(bbox, (10, 120, 320, 140))


if __name__ == "__main__":
    unittest.main()
