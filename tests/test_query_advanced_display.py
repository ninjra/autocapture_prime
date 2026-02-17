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

    def test_adv_arbitrates_between_hard_and_structured_claim_sources(self) -> None:
        claim_sources = [
            {
                "provider_id": "builtin.observation.graph",
                "doc_kind": "adv.window.inventory",
                "record_id": "rec7",
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
                        "source_backend": "openai_compat_two_pass",
                        "vlm_grounded": True,
                    }
                },
            }
        ]
        hard_vlm = {
            "windows": [
                {"name": "Wrong A", "app": "Wrong A", "context": "host", "visibility": "fully_visible", "z_order": 1},
                {"name": "Wrong B", "app": "Wrong B", "context": "host", "visibility": "fully_visible", "z_order": 2},
            ]
        }
        display = query_mod._build_answer_display(
            "Enumerate every distinct top-level window visible in the screenshot in z-order.",
            [],
            claim_sources,
            hard_vlm=hard_vlm,
        )
        self.assertEqual(display.get("topic"), "adv_window_inventory")
        bullets = [str(x) for x in display.get("bullets", [])]
        self.assertTrue(any("Slack DM" in b for b in bullets))
        self.assertFalse(any("Wrong A" in b for b in bullets))

    def test_adv_calendar_non_numeric_item_count_does_not_crash(self) -> None:
        claim_sources = [
            {
                "provider_id": "builtin.observation.graph",
                "doc_kind": "adv.calendar.schedule",
                "record_id": "rec_cal",
                "signal_pairs": {
                    "adv.calendar.month_year": "January 2026",
                    "adv.calendar.selected_date": "2",
                    "adv.calendar.item_count": "Not found",
                    "adv.calendar.item.1.start": "8:00 AM",
                    "adv.calendar.item.1.title": "CS Daily Standup",
                },
                "meta": {
                    "meta": {
                        "source_modality": "vlm",
                        "source_state_id": "vlm",
                        "source_backend": "openai_compat_two_pass",
                        "vlm_grounded": True,
                    }
                },
            }
        ]
        display = query_mod._build_adv_display("adv_calendar", claim_sources)
        self.assertIsNotNone(display)
        display = display or {}
        self.assertEqual(display.get("topic"), "adv_calendar")
        self.assertIn("January 2026", str(display.get("summary") or ""))

    def test_normalize_hard_fields_parses_answer_text_for_focus(self) -> None:
        hard = {
            "answer_text": '{"focused_window":"Outlook (VDI)","evidence":[{"kind":"selected_message","text":"Task Set Up Open Invoice"}]}'
        }
        norm = query_mod._normalize_hard_fields_for_topic("adv_focus", hard)
        self.assertEqual(str(norm.get("focused_window") or ""), "Outlook (VDI)")
        self.assertEqual(str(norm.get("window") or ""), "Outlook (VDI)")
        self.assertTrue(isinstance(norm.get("evidence"), list))

    def test_hard_vlm_merge_windows_prefers_consensus_entries(self) -> None:
        candidates = [
            {
                "score": 28,
                "source": "grid8",
                "section_id": "grid_1",
                "payload": {
                    "windows": [
                        {"name": "Slack", "app": "Slack", "context": "host"},
                        {"name": "WrongSolo", "app": "WrongSolo", "context": "host"},
                    ]
                },
            },
            {
                "score": 30,
                "source": "grid8",
                "section_id": "grid_2",
                "payload": {"windows": [{"name": "Slack", "app": "Slack", "context": "host"}]},
            },
            {
                "score": 36,
                "source": "roi",
                "section_id": "roi_1",
                "payload": {"windows": [{"name": "ChatGPT", "app": "ChatGPT", "context": "host"}]},
            },
        ]
        merged = query_mod._hard_vlm_merge_windows(  # type: ignore[attr-defined]
            candidates,
            key_fields=("name", "app", "context"),
            consensus_min_hits=2,
            keep_if_score_at_least=34,
        )
        keys = {f"{str(x.get('name') or '')}|{str(x.get('app') or '')}" for x in merged if isinstance(x, dict)}
        self.assertIn("Slack|Slack", keys)
        self.assertIn("ChatGPT|ChatGPT", keys)
        self.assertNotIn("WrongSolo|WrongSolo", keys)

    def test_hard_vlm_merge_windows_fallback_keeps_items_when_no_consensus(self) -> None:
        candidates = [
            {
                "score": 22,
                "source": "grid8",
                "section_id": "grid_3",
                "payload": {"windows": [{"name": "OnlyOne", "app": "OnlyOne", "context": "host"}]},
            }
        ]
        merged = query_mod._hard_vlm_merge_windows(  # type: ignore[attr-defined]
            candidates,
            key_fields=("name", "app", "context"),
            consensus_min_hits=3,
            keep_if_score_at_least=99,
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(str(merged[0].get("name") or ""), "OnlyOne")

    def test_normalize_hard_fields_parses_answer_text_for_details(self) -> None:
        hard = {"answer_text": '[{"label":"Service requestor","value":"Norry Mata"}]'}
        norm = query_mod._normalize_hard_fields_for_topic("adv_details", hard)
        fields = norm.get("fields")
        self.assertTrue(isinstance(fields, list))
        self.assertEqual(str(fields[0].get("label") or ""), "Service requestor")

    def test_extract_json_payload_accepts_array_wrapper(self) -> None:
        raw = "prefix [{\"label\":\"A\",\"value\":\"B\"}] suffix"
        parsed = query_mod._extract_json_payload(raw)
        self.assertTrue(isinstance(parsed, list))
        self.assertEqual(str(parsed[0].get("label") or ""), "A")


if __name__ == "__main__":
    unittest.main()
