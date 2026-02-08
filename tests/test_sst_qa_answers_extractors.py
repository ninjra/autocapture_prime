import unittest


class SSTQAAnswersExtractorsTests(unittest.TestCase):
    def test_count_inboxes_counts_multiword_tokens(self) -> None:
        from plugins.builtin.sst_qa_answers import plugin as qa

        tokens = [
            {"text": "M Inbox", "bbox": [100, 10, 160, 30]},
            {"text": "M Inbox", "bbox": [400, 10, 460, 30]},
            # Sidebar "Inbox" label should not count as an additional open inbox tab.
            {"text": "Inbox", "bbox": [900, 600, 940, 640]},
            # Noise that should not count.
            {"text": "Inboxes", "bbox": [900, 260, 980, 300]},
            {"text": "Inboxing", "bbox": [10, 500, 90, 520]},
        ]
        # Two distinct top-bar inbox tabs should count as two open inboxes.
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

    def test_extract_quorum_collaborator_ignores_yesyes_garbage(self) -> None:
        from plugins.builtin.sst_qa_answers import plugin as qa

        tokens = [
            {"text": "taskwasassignedtoYesYes", "bbox": [10, 120, 320, 140]},
            {"text": "taskwasassignedtoOpenInvoice", "bbox": [10, 160, 320, 180]},
        ]
        collaborator, _bbox = qa._extract_quorum_collaborator(tokens)
        self.assertEqual(collaborator, "Open Invoice")


if __name__ == "__main__":
    unittest.main()
