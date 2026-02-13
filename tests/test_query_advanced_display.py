import unittest

from autocapture_nx.kernel import query as query_mod


class QueryAdvancedDisplayTests(unittest.TestCase):
    def test_parse_observation_pairs_keeps_domain_periods(self) -> None:
        text = (
            "Observation: adv.incident.sender_domain=permianres.com; "
            "adv.incident.subject=A task was assigned to Open Invoice."
        )
        pairs = query_mod._parse_observation_pairs(text)
        self.assertEqual(pairs.get("adv.incident.sender_domain"), "permianres.com")
        self.assertEqual(pairs.get("adv.incident.subject"), "A task was assigned to Open Invoice")

    def test_advanced_incident_display_domain_only(self) -> None:
        claim_sources = [
            {
                "provider_id": "builtin.observation.graph",
                "doc_kind": "adv.incident.card",
                "record_id": "rec1",
                "signal_pairs": {
                    "adv.incident.subject": "A task was assigned to Open Invoice",
                    "adv.incident.sender_display": "Permian Resources Service Desk",
                    "adv.incident.sender_domain": "servicedesk@permianres.com",
                    "adv.incident.action_buttons": "COMPLETE|VIEW DETAILS",
                },
                "meta": {
                    "meta": {
                        "source_modality": "vlm",
                        "source_state_id": "vlm",
                        "source_backend": "openai_compat_layout",
                        "vlm_grounded": True,
                    }
                },
            }
        ]
        display = query_mod._build_answer_display(
            "In the VDI Outlook reading pane showing a task/incident email: extract subject, sender domain, and action buttons.",
            [],
            claim_sources,
        )
        self.assertEqual(display.get("topic"), "adv_incident")
        self.assertIn("domain=permianres.com", str(display.get("summary") or ""))
        joined = "\n".join(str(x) for x in display.get("bullets", []))
        self.assertIn("COMPLETE", joined)
        self.assertIn("VIEW DETAILS", joined)

    def test_advanced_window_inventory_display(self) -> None:
        claim_sources = [
            {
                "provider_id": "builtin.observation.graph",
                "doc_kind": "adv.window.inventory",
                "record_id": "rec2",
                "signal_pairs": {
                    "adv.window.count": "2",
                    "adv.window.1.app": "Slack DM",
                    "adv.window.1.context": "host",
                    "adv.window.1.visibility": "partially_occluded",
                    "adv.window.1.z_order": "1",
                    "adv.window.2.app": "Outlook (VDI)",
                    "adv.window.2.context": "vdi",
                    "adv.window.2.visibility": "fully_visible",
                    "adv.window.2.z_order": "2",
                },
                "meta": {
                    "meta": {
                        "source_modality": "vlm",
                        "source_state_id": "vlm",
                        "source_backend": "openai_compat_layout",
                        "vlm_grounded": True,
                    }
                },
            }
        ]
        display = query_mod._build_answer_display(
            "Enumerate every distinct top-level window visible in the screenshot in z-order.",
            [],
            claim_sources,
        )
        self.assertEqual(display.get("topic"), "adv_window_inventory")
        self.assertEqual(display.get("summary"), "Visible top-level windows: 2")
        bullets = [str(x) for x in display.get("bullets", [])]
        self.assertTrue(any("Slack DM" in b for b in bullets))
        self.assertTrue(any("Outlook (VDI)" in b for b in bullets))

    def test_advanced_display_blocks_ocr_only_sources(self) -> None:
        claim_sources = [
            {
                "provider_id": "builtin.observation.graph",
                "doc_kind": "adv.window.inventory",
                "record_id": "rec3",
                "signal_pairs": {
                    "adv.window.count": "3",
                    "adv.window.1.app": "Outlook",
                    "adv.window.1.context": "vdi",
                    "adv.window.1.visibility": "fully_visible",
                },
                "meta": {
                    "meta": {
                        "source_modality": "ocr",
                        "source_state_id": "pending",
                        "source_backend": "heuristic",
                        "vlm_grounded": False,
                    }
                },
            }
        ]
        display = query_mod._build_answer_display(
            "Enumerate every distinct top-level window visible in the screenshot in z-order.",
            [],
            claim_sources,
        )
        self.assertEqual(display.get("topic"), "adv_window_inventory")
        self.assertIn("Indeterminate", str(display.get("summary") or ""))

    def test_standard_signal_blocks_ocr_only(self) -> None:
        claim_sources = [
            {
                "provider_id": "builtin.observation.graph",
                "doc_kind": "obs.metric.open_inboxes",
                "record_id": "rec4",
                "signal_pairs": {"open_inboxes_count": "4"},
                "meta": {
                    "meta": {
                        "source_modality": "ocr",
                        "source_state_id": "pending",
                        "source_backend": "heuristic",
                        "vlm_grounded": False,
                    }
                },
            }
        ]
        display = query_mod._build_answer_display("how many inboxes do i have open", [], claim_sources)
        self.assertEqual(display.get("topic"), "inbox")
        self.assertIn("Indeterminate", str(display.get("summary") or ""))

    def test_standard_signal_allows_vlm_grounded(self) -> None:
        claim_sources = [
            {
                "provider_id": "builtin.observation.graph",
                "doc_kind": "obs.metric.open_inboxes",
                "record_id": "rec5",
                "signal_pairs": {"open_inboxes_count": "4"},
                "meta": {
                    "meta": {
                        "source_modality": "vlm",
                        "source_state_id": "vlm",
                        "source_backend": "openai_compat_layout",
                        "vlm_grounded": True,
                    }
                },
            }
        ]
        display = query_mod._build_answer_display("how many inboxes do i have open", [], claim_sources)
        self.assertEqual(display.get("topic"), "inbox")
        self.assertEqual(display.get("summary"), "Open inboxes: 4")

    def test_standard_signal_allows_top_level_vlm_meta(self) -> None:
        claim_sources = [
            {
                "provider_id": "builtin.observation.graph",
                "doc_kind": "obs.metric.open_inboxes",
                "record_id": "rec6",
                "signal_pairs": {"open_inboxes_count": "3"},
                "meta": {
                    "source_modality": "vlm",
                    "source_state_id": "vlm",
                    "source_backend": "openai_compat_two_pass",
                    "vlm_grounded": True,
                    "vlm_element_count": 1,
                },
            }
        ]
        display = query_mod._build_answer_display("how many inboxes do i have open", [], claim_sources)
        self.assertEqual(display.get("topic"), "inbox")
        self.assertEqual(display.get("summary"), "Open inboxes: 3")


if __name__ == "__main__":
    unittest.main()
