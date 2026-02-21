import unittest


class SSTQAAnswersExtractorsTests(unittest.TestCase):
    def test_extract_vdi_time_prefers_non_host_taskbar_clock(self) -> None:
        from plugins.builtin.sst_qa_answers import plugin as qa

        # Two clocks: a host taskbar clock at the absolute bottom, and a VDI
        # clock slightly above. The extractor should pick the VDI clock.
        tokens = [
            {"text": "12:55 PM", "bbox": [1800, 980, 1900, 1000]},  # host taskbar
            {"text": "11:55 AM", "bbox": [1700, 860, 1780, 880]},  # VDI taskbar
        ]
        value, _bbox = qa._extract_vdi_time(tokens)
        self.assertEqual(value, "11:55 AM")

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

    def test_collect_inbox_signals_combines_token_and_line_contexts(self) -> None:
        from plugins.builtin.sst_qa_answers import plugin as qa

        tokens = [
            {"text": "Inbox", "bbox": [1600, 320, 1900, 340]},
            {"text": "Inbox", "bbox": [2200, 610, 2450, 630]},
        ]
        text_lines = [
            {"text": "SiriusXM | Inbox | browser tabs", "bbox": [0, 320, 7600, 335]},
            {"text": "Remote desktop | M Inbox | web client", "bbox": [0, 610, 7600, 625]},
            {"text": "File New Home ChatGPT Email Send/Receive", "bbox": [0, 640, 7600, 655]},
            {"text": "Received 7:41 AM Contractor Agency Email", "bbox": [0, 1330, 7600, 1345]},
        ]

        signals = qa._collect_inbox_signals(tokens, text_lines=text_lines)
        self.assertEqual(int(signals.get("token_count", 0)), 2)
        self.assertEqual(int(signals.get("line_count", 0)), 4)
        self.assertEqual(int(signals.get("mail_context_count", 0)), 2)
        self.assertEqual(int(signals.get("count", 0)), 4)
        self.assertGreaterEqual(len(signals.get("token_hits", [])), 2)
        self.assertGreaterEqual(len(signals.get("line_hits", [])), 4)
        self.assertGreaterEqual(len(signals.get("mail_context_hits", [])), 2)

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

    def test_extract_quorum_collaborator_prefers_human_over_open_invoice_group(self) -> None:
        from plugins.builtin.sst_qa_answers import plugin as qa

        tokens = [
            {"text": "taskwasassignedtoOpenInvoice", "bbox": [10, 120, 320, 140]},
            # Teams header row: "Copilot Alice Smith"
            {"text": "Copilot", "bbox": [10, 10, 80, 30]},
            {"text": "Alice", "bbox": [90, 10, 140, 30]},
            {"text": "Smith", "bbox": [150, 10, 210, 30]},
        ]
        collaborator, _bbox = qa._extract_quorum_collaborator(tokens)
        self.assertEqual(collaborator, "Alice Smith")

    def test_extract_quorum_collaborator_prefers_contractor_over_open_invoice(self) -> None:
        from plugins.builtin.sst_qa_answers import plugin as qa

        tokens = [
            {"text": "taskwasassignedtoOpenInvoice", "bbox": [10, 120, 320, 140]},
            # Task title line: "... for Contractor Alice Smith ..."
            {"text": "for", "bbox": [10, 200, 30, 220]},
            {"text": "Contractor", "bbox": [40, 200, 120, 220]},
            {"text": "Alice", "bbox": [130, 200, 180, 220]},
            {"text": "Smith", "bbox": [190, 200, 250, 220]},
        ]
        collaborator, _bbox = qa._extract_quorum_collaborator(tokens)
        self.assertEqual(collaborator, "Alice Smith")

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
