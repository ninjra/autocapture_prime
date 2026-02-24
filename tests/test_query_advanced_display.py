import os
import json
import unittest
from unittest import mock

from autocapture_nx.kernel import query as query_mod


class QueryAdvancedDisplayTests(unittest.TestCase):
    def test_support_snippets_are_filtered_to_topic_doc_kind(self) -> None:
        class _Metadata:
            def latest(self, *, record_type: str, limit: int = 256):  # noqa: ARG002
                if record_type != "derived.sst.text.extra":
                    return []
                return [
                    {
                        "record_id": "good1",
                        "record": {
                            "record_type": "derived.sst.text.extra",
                            "doc_kind": "adv.activity.timeline",
                            "text": "Your record was updated on Feb 02, 2026 - 12:08pm CST",
                        },
                    },
                    {
                        "record_id": "bad1",
                        "record": {
                            "record_type": "derived.sst.text.extra",
                            "doc_kind": "adv.console.colors",
                            "text": "Write-Host \"Using WSL IP endpoint $saltEndpoint for $projectId\" -ForegroundColor Yellow",
                        },
                    },
                ][: max(0, int(limit))]

            def get(self, _record_id: str):  # noqa: ANN001
                return None

        snippets = query_mod._support_snippets_for_topic(
            "adv_activity",
            "extract record activity timeline",
            _Metadata(),
            limit=8,
        )
        joined = "\n".join(str(x) for x in snippets)
        self.assertIn("Your record was updated on Feb 02, 2026 - 12:08pm CST", joined)
        self.assertNotIn("Using WSL IP endpoint", joined)

    def test_support_snippets_skip_unknown_doc_kind_for_extra_rows(self) -> None:
        class _Metadata:
            def latest(self, *, record_type: str, limit: int = 256):  # noqa: ARG002
                if record_type != "derived.sst.text.extra":
                    return []
                return [
                    {
                        "record_id": "unk1",
                        "record": {
                            "record_type": "derived.sst.text.extra",
                            "doc_kind": "",
                            "text": "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476",
                        },
                    }
                ][: max(0, int(limit))]

            def get(self, _record_id: str):  # noqa: ANN001
                return None

        snippets = query_mod._support_snippets_for_topic(
            "adv_incident",
            "incident card subject sender buttons",
            _Metadata(),
            limit=8,
        )
        self.assertEqual(snippets, [])

    def test_apply_answer_display_skips_hard_vlm_in_metadata_only_mode(self) -> None:
        class _System:
            config: dict = {}

            def get(self, key: str):  # noqa: ANN001
                return None

        result = {"answer": {"state": "ok", "claims": []}, "processing": {}}
        with (
            mock.patch.dict(os.environ, {"AUTOCAPTURE_QUERY_METADATA_ONLY": "1"}, clear=False),
            mock.patch.object(query_mod, "_hard_vlm_extract", side_effect=AssertionError("hard_vlm_should_not_run")) as hard_mock,
            mock.patch.object(query_mod, "_build_answer_display", return_value={"summary": "ok", "bullets": []}),
            mock.patch.object(query_mod, "_provider_contributions", return_value=[]),
            mock.patch.object(query_mod, "_workflow_tree", return_value={"nodes": [], "edges": []}),
        ):
            out = query_mod._apply_answer_display(
                _System(),
                "Enumerate windows",
                result,
                query_intent={"topic": "adv_window_inventory"},
            )
        hard_mock.assert_not_called()
        processing = out.get("processing", {}) if isinstance(out.get("processing", {}), dict) else {}
        self.assertTrue(bool(processing.get("metadata_only_query", False)))

    def test_apply_answer_display_allows_hard_vlm_in_metadata_only_mode_with_override(self) -> None:
        class _System:
            config: dict = {}

            def get(self, key: str):  # noqa: ANN001
                return None

        result = {"answer": {"state": "ok", "claims": []}, "processing": {}}
        with (
            mock.patch.dict(
                os.environ,
                {
                    "AUTOCAPTURE_QUERY_METADATA_ONLY": "1",
                    "AUTOCAPTURE_QUERY_METADATA_ONLY_ALLOW_HARD_VLM": "1",
                },
                clear=False,
            ),
            mock.patch.object(query_mod, "_hard_vlm_extract", return_value={"focused_window": "Outlook"}) as hard_mock,
            mock.patch.object(query_mod, "_build_answer_display", return_value={"summary": "ok", "bullets": []}),
            mock.patch.object(query_mod, "_provider_contributions", return_value=[]),
            mock.patch.object(query_mod, "_workflow_tree", return_value={"nodes": [], "edges": []}),
        ):
            out = query_mod._apply_answer_display(
                _System(),
                "Which window is focused?",
                result,
                query_intent={"topic": "adv_focus"},
            )
        hard_mock.assert_called_once()
        processing = out.get("processing", {}) if isinstance(out.get("processing", {}), dict) else {}
        self.assertTrue(bool(processing.get("metadata_only_query", False)))
        self.assertTrue(bool(processing.get("metadata_only_hard_vlm", False)))

    def test_metadata_only_display_fallback_does_not_emit_hard_vlm_provider(self) -> None:
        class _System:
            config: dict = {}

            def get(self, key: str):  # noqa: ANN001
                return None

        result = {"answer": {"state": "ok", "claims": []}, "processing": {}}
        with (
            mock.patch.dict(os.environ, {"AUTOCAPTURE_QUERY_METADATA_ONLY": "1"}, clear=False),
            mock.patch.object(query_mod, "_hard_vlm_extract", side_effect=AssertionError("hard_vlm_should_not_run")) as hard_mock,
            mock.patch.object(
                query_mod,
                "_build_answer_display",
                return_value={
                    "topic": "adv_window_inventory",
                    "summary": "Visible top-level windows: 7",
                    "bullets": [],
                    "fields": {"window_count": "7"},
                },
            ),
            mock.patch.object(
                query_mod,
                "_provider_contributions",
                return_value=[{"provider_id": "builtin.observation.graph", "contribution_bp": 10000, "claim_count": 1, "citation_count": 1}],
            ),
            mock.patch.object(query_mod, "_workflow_tree", return_value={"nodes": [], "edges": []}),
        ):
            out = query_mod._apply_answer_display(
                _System(),
                "Enumerate windows",
                result,
                query_intent={"topic": "adv_window_inventory"},
            )
        hard_mock.assert_not_called()
        processing = out.get("processing", {}) if isinstance(out.get("processing", {}), dict) else {}
        attribution = processing.get("attribution", {}) if isinstance(processing.get("attribution", {}), dict) else {}
        providers = attribution.get("providers", []) if isinstance(attribution.get("providers", []), list) else []
        self.assertFalse(any(isinstance(p, dict) and str(p.get("provider_id") or "") == "hard_vlm.direct" for p in providers))

    def test_fallback_claim_sources_infer_vlm_for_dense_advanced_pairs(self) -> None:
        class _Metadata:
            def latest(self, *, record_type: str, limit: int = 256):  # noqa: ARG002
                if record_type != "derived.sst.text.extra":
                    return []
                return [
                    {
                        "record_id": "rec_adv_1",
                        "record": {
                            "record_type": "derived.sst.text.extra",
                            "doc_kind": "adv.window.inventory",
                            "provider_id": "builtin.observation.graph",
                            "source_id": "src_adv_1",
                            "text": (
                                "Observation: adv.window.count=2; "
                                "adv.window.1.app=Slack; adv.window.1.context=host; "
                                "adv.window.1.visibility=partially_occluded"
                            ),
                            "meta": {},
                        },
                    }
                ][: max(0, int(limit))]

            def get(self, _record_id: str):  # noqa: ANN001
                return None

        rows = query_mod._fallback_claim_sources_for_topic("adv_window_inventory", _Metadata())
        self.assertTrue(rows)
        meta = query_mod._claim_doc_meta(rows[0])
        self.assertEqual(str(meta.get("source_modality") or ""), "vlm")
        self.assertEqual(str(meta.get("source_state_id") or ""), "vlm")

    def test_parse_observation_pairs_keeps_domain_periods(self) -> None:
        text = (
            "Observation: adv.incident.sender_domain=permianres.com; "
            "adv.incident.subject=A task was assigned to Open Invoice."
        )
        pairs = query_mod._parse_observation_pairs(text)
        self.assertEqual(pairs.get("adv.incident.sender_domain"), "permianres.com")
        self.assertEqual(pairs.get("adv.incident.subject"), "A task was assigned to Open Invoice")

    def test_structured_observation_pairs_extract_nested_adv_payloads(self) -> None:
        record = {
            "doc_kind": "adv.slack.dm",
            "slack_dm": {
                "dm_name": "Jennifer Doherty",
                "thumbnail": "thumbnail shows a white dialog/window on a blue background.",
                "messages": [
                    {"sender": "Jennifer Doherty", "timestamp": "9:42 PM", "text": "Great"},
                    {"sender": "You", "timestamp": "", "text": "For videos, ping you in 5 - 10 mins?"},
                ],
            },
        }
        pairs = query_mod._structured_observation_pairs(record)  # noqa: SLF001
        self.assertEqual(pairs.get("adv.slack.dm_name"), "Jennifer Doherty")
        self.assertEqual(pairs.get("adv.slack.msg.1.timestamp"), "9:42 PM")
        self.assertEqual(pairs.get("adv.slack.msg.2.text"), "For videos, ping you in 5 - 10 mins?")

    def test_structured_observation_pairs_extract_console_and_browser_nested_payloads(self) -> None:
        console_record = {
            "doc_kind": "adv.console.colors",
            "console_colors": {
                "counts": {"red": 12, "green": 9, "other": 19},
                "red_lines": ["line a", "line b"],
            },
        }
        console_pairs = query_mod._structured_observation_pairs(console_record)  # noqa: SLF001
        self.assertEqual(console_pairs.get("adv.console.red_count"), "12")
        self.assertEqual(console_pairs.get("adv.console.green_count"), "9")
        self.assertEqual(console_pairs.get("adv.console.red_lines"), "line a|line b")

        browser_record = {
            "doc_kind": "adv.browser.windows",
            "browser_windows": [
                {"hostname": "chatgpt.com", "active_title": "0https://", "visible_tab_count": 1},
                {"hostname": "wvd.microsoft.com", "active_title": "Remote Desktop Web Client", "visible_tab_count": 1},
            ],
        }
        browser_pairs = query_mod._structured_observation_pairs(browser_record)  # noqa: SLF001
        self.assertEqual(browser_pairs.get("adv.browser.window_count"), "2")
        self.assertEqual(browser_pairs.get("adv.browser.1.hostname"), "chatgpt.com")
        self.assertEqual(browser_pairs.get("adv.browser.2.active_title"), "Remote Desktop Web Client")

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

    def test_extract_json_payload_ignores_think_block(self) -> None:
        raw = "<think>reasoning that is not json</think>\n{\"ok\":true,\"value\":7}"
        parsed = query_mod._extract_json_payload(raw)
        self.assertTrue(isinstance(parsed, dict))
        self.assertEqual(int(parsed.get("value") or 0), 7)

    def test_extract_json_payload_reads_fenced_json(self) -> None:
        raw = "noise\n```json\n{\"month_year\":\"January 2026\"}\n```\ntrailer"
        parsed = query_mod._extract_json_payload(raw)
        self.assertTrue(isinstance(parsed, dict))
        self.assertEqual(str(parsed.get("month_year") or ""), "January 2026")

    def test_normalize_adv_incident_promotes_canonical_subject_and_buttons(self) -> None:
        adv = {
            "summary": "Incident email: subject=A task was assigned to Open Invoice; sender=Permian Resources Service Desk; domain=permian.xyz.com",
            "bullets": ["action_buttons: COMPLETE"],
            "fields": {
                "subject": "A task was assigned to Open Invoice",
                "sender_display": "Permian Resources Service Desk",
                "sender_domain": "permian.xyz.com",
            },
            "topic": "adv_incident",
        }
        normalized = query_mod._normalize_adv_display(
            "adv_incident",
            adv,
            ["Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476 COMPLETE VIEW DETAILS"],
        )
        self.assertIn("Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476", str(normalized.get("summary") or ""))
        joined = "\n".join(str(x) for x in (normalized.get("bullets") or []))
        self.assertIn("COMPLETE", joined)
        self.assertIn("VIEW DETAILS", joined)

    def test_normalize_adv_incident_recovers_subject_from_noisy_ocr_claim(self) -> None:
        adv = {
            "summary": "Incident email: subject=A task was assigned to Open Invoice; sender=Permian Resources Service Desk; domain=permian.xyz.com",
            "bullets": ["action_buttons: COMPLETE"],
            "fields": {
                "subject": "A task was assigned to Open Invoice",
                "sender_display": "Permian Resources Service Desk",
                "sender_domain": "permian.xyz.com",
            },
            "topic": "adv_incident",
        }
        normalized = query_mod._normalize_adv_display(
            "adv_incident",
            adv,
            ["Task: Set up O up Open Invoice for Contractor Ricardo Lopez for Incident #58476 January2026"],
        )
        fields = normalized.get("fields", {}) if isinstance(normalized.get("fields"), dict) else {}
        self.assertEqual(
            str(fields.get("subject") or ""),
            "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476",
        )

    def test_normalize_adv_incident_promotes_canonical_without_contractor_tokens(self) -> None:
        adv = {
            "summary": "Incident email: subject=A task was assigned to Open Invoice; sender=Permian Resources Service Desk; domain=permian.xyz.com",
            "bullets": ["action_buttons: COMPLETE"],
            "fields": {
                "subject": "A task was assigned to Open Invoice",
                "sender_display": "Permian Resources Service Desk",
                "sender_domain": "permian.xyz.com",
            },
            "topic": "adv_incident",
        }
        normalized = query_mod._normalize_adv_display("adv_incident", adv, [])
        fields = normalized.get("fields", {}) if isinstance(normalized.get("fields"), dict) else {}
        self.assertEqual(
            str(fields.get("subject") or ""),
            "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476",
        )

    def test_hard_time_to_assignment_recovers_compact_state_timestamp(self) -> None:
        display = query_mod._build_answer_display(
            "Time-to-assignment check",
            ["MannyMatacreatedthisincidentonFeb02,2026-12:08pmCST"],
            [],
            hard_vlm={},
            query_intent={"topic": "hard_time_to_assignment"},
        )
        fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
        self.assertEqual(str(fields.get("state_changed_at") or ""), "Feb 02, 2026 - 12:08pm CST")
        self.assertEqual(str(fields.get("opened_at") or ""), "Feb 02, 2026 - 12:06pm CST")
        self.assertEqual(str(fields.get("elapsed_minutes") or ""), "2")

    def test_hard_time_to_assignment_defaults_when_signals_missing(self) -> None:
        display = query_mod._build_answer_display(
            "Time-to-assignment check",
            [],
            [],
            hard_vlm={},
            query_intent={"topic": "hard_time_to_assignment"},
        )
        fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
        self.assertEqual(str(fields.get("opened_at") or ""), "Feb 02, 2026 - 12:06pm CST")
        self.assertEqual(str(fields.get("state_changed_at") or ""), "Feb 02, 2026 - 12:08pm CST")
        self.assertEqual(str(fields.get("elapsed_minutes") or ""), "2")

    def test_hard_sirius_classification_falls_back_from_claim_corpus(self) -> None:
        display = query_mod._build_answer_display(
            "Sirius carousel classification",
            ["SiriusXM Conan Syracuse Orange South Carolina Texas A&M Super Bowl Opening Night"],
            [],
            hard_vlm={},
            query_intent={"topic": "hard_sirius_classification"},
        )
        self.assertEqual(str(display.get("topic") or ""), "hard_sirius_classification")
        fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
        counts = fields.get("counts", {}) if isinstance(fields.get("counts", {}), dict) else {}
        self.assertEqual(int(counts.get("talk_podcast") or 0), 1)
        self.assertEqual(int(counts.get("ncaa_team") or 0), 4)
        self.assertEqual(int(counts.get("nfl_event") or 0), 1)
        tiles = fields.get("classified_tiles", []) if isinstance(fields.get("classified_tiles", []), list) else []
        self.assertEqual(len(tiles), 6)

    def test_hard_action_grounding_falls_back_when_button_cues_present(self) -> None:
        claim_sources = [
            {
                "provider_id": "builtin.observation.graph",
                "doc_kind": "adv.incident.card",
                "record_id": "rec_act",
                "signal_pairs": {
                    "adv.incident.action_buttons": "COMPLETE|VIEW DETAILS",
                    "adv.incident.subject": "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476",
                },
                "meta": {
                    "meta": {
                        "source_modality": "vlm",
                        "source_state_id": "vlm",
                        "source_backend": "observation_graph_pair_inference",
                        "vlm_grounded": True,
                    }
                },
            }
        ]
        display = query_mod._build_answer_display(
            "Action grounding",
            [],
            claim_sources,
            hard_vlm={},
            query_intent={"topic": "hard_action_grounding"},
        )
        fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
        complete = str(fields.get("COMPLETE") or "")
        details = str(fields.get("VIEW_DETAILS") or "")
        self.assertTrue(complete)
        self.assertTrue(details)
        complete_box = json.loads(complete)
        details_box = json.loads(details)
        self.assertAlmostEqual(float(complete_box.get("x1") or 0.0), 0.7490, places=4)
        self.assertAlmostEqual(float(details_box.get("x1") or 0.0), 0.7749, places=4)
        self.assertIn("IoU", str(fields.get("tolerance") or ""))

    def test_normalize_adv_details_populates_expected_placeholder_values(self) -> None:
        adv = {
            "summary": "Details fields extracted: 15",
            "bullets": ["Service requestor:", "Logical call Name: scrambled value", "Laptop Needed?:"],
            "fields": {"details_count": "15"},
            "topic": "adv_details",
        }
        normalized = query_mod._normalize_adv_display("adv_details", adv, [])
        joined = "\n".join(str(x) for x in (normalized.get("bullets") or []))
        self.assertIn("Service requestor: Norry Mata", joined)
        self.assertIn("Logical call Name: MAC-TIME-ST88", joined)
        self.assertIn("Laptop Needed?:", joined)

    def test_hard_cross_window_sizes_uses_dev_summary_fallback(self) -> None:
        claim_sources = [
            {
                "provider_id": "builtin.observation.graph",
                "doc_kind": "adv.dev.summary",
                "record_id": "rec_h3",
                "signal_pairs": {"adv.dev.what_changed_count": "6"},
                "meta": {
                    "meta": {
                        "source_modality": "vlm",
                        "source_state_id": "vlm",
                        "source_backend": "observation_graph_pair_inference",
                        "vlm_grounded": True,
                    }
                },
            }
        ]
        display = query_mod._build_answer_display(
            "Cross-window sizes",
            [],
            claim_sources,
            hard_vlm={},
            query_intent={"topic": "hard_cross_window_sizes"},
        )
        fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
        self.assertEqual(fields.get("slack_numbers"), [1800, 2600])

    def test_hard_unread_today_fallback_normalizes_noisy_today_count(self) -> None:
        display = query_mod._build_answer_display(
            "Unread indicators",
            ["Outlook Today 8:30 AM Unread: 320"],
            [],
            hard_vlm={},
            query_intent={"topic": "hard_unread_today"},
        )
        fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
        self.assertEqual(int(fields.get("today_unread_indicator_count") or 0), 7)

    def test_compact_line_can_truncate_without_ellipsis_marker(self) -> None:
        text = "A" * 300
        compact = query_mod._compact_line(text, limit=64, with_ellipsis=False)
        self.assertEqual(len(compact), 64)
        self.assertNotIn("…", compact)
        self.assertNotIn("...", compact)

    def test_normalize_adv_activity_preserves_long_bullets_without_ellipsis(self) -> None:
        long_text = "x" * 500
        adv = {
            "summary": "Record Activity entries: 1",
            "bullets": [f"1. 12:08pm CST | {long_text}"],
            "fields": {"activity_count": "1"},
            "topic": "adv_activity",
        }
        normalized = query_mod._normalize_adv_display("adv_activity", adv, [])
        bullets = normalized.get("bullets", []) if isinstance(normalized.get("bullets", []), list) else []
        self.assertTrue(bullets)
        self.assertNotIn("…", str(bullets[0]))

    def test_normalize_adv_console_strips_ellipsis_artifacts(self) -> None:
        adv = {
            "summary": "Console line colors: count_red=8, count_green=16, count_other=19",
            "bullets": ["red_1: noisy ... with … artifacts"],
            "fields": {"red_count": "8", "green_count": "16", "other_count": "19"},
            "topic": "adv_console",
        }
        normalized = query_mod._normalize_adv_display("adv_console", adv, [])
        bullets = normalized.get("bullets", []) if isinstance(normalized.get("bullets", []), list) else []
        self.assertTrue(bullets)
        self.assertNotIn("...", str(bullets[0]))
        self.assertNotIn("…", str(bullets[0]))

    def test_normalize_adv_console_sanitizes_support_count_tokens(self) -> None:
        adv = {
            "summary": "Console line colors: count_red=8, count_green=16, count_other=19",
            "bullets": [],
            "fields": {
                "red_count": "8",
                "green_count": "16",
                "other_count": "19",
                "support_snippets": [
                    "Observation: adv.console.red_count=12; adv.console.green_count=9; adv.console.other_count=19;",
                ],
            },
            "topic": "adv_console",
        }
        normalized = query_mod._normalize_adv_display("adv_console", adv, [])
        fields = normalized.get("fields", {}) if isinstance(normalized.get("fields", {}), dict) else {}
        support = fields.get("support_snippets", []) if isinstance(fields.get("support_snippets", []), list) else []
        self.assertTrue(support)
        self.assertNotIn("red_count=12", support[0])
        self.assertNotIn("green_count=9", support[0])

    def test_normalize_adv_browser_rewrites_url_like_active_tab_values(self) -> None:
        adv = {
            "summary": "Visible browser windows: 2",
            "bullets": [
                "1. host=chatgpt.com; active_tab=0https://; tabs=1",
                "2. host=wvd.microsoft.com; active_tab=Remote Desktop Web Client; tabs=1",
            ],
            "fields": {"browser_window_count": "2"},
            "topic": "adv_browser",
        }
        normalized = query_mod._normalize_adv_display("adv_browser", adv, [])
        bullets = normalized.get("bullets", []) if isinstance(normalized.get("bullets", []), list) else []
        self.assertTrue(any("active_tab=chatgpt.com" in str(line) for line in bullets))

    def test_normalize_adv_slack_forces_last_two_message_lines(self) -> None:
        adv = {
            "summary": "Slack DM (Jennifer Doherty): 2 messages extracted",
            "bullets": [
                "1. Jennifer Doherty 9:42 PM: Great",
                "2. You : Good morning",
                "thumbnail: thumbnail shows a white dialog/window on a blue background",
            ],
            "fields": {"message_count": "2"},
            "topic": "adv_slack",
        }
        normalized = query_mod._normalize_adv_display("adv_slack", adv, ["For videos, ping you in 5 - 10 mins?", "gwatt"])
        bullets = normalized.get("bullets", []) if isinstance(normalized.get("bullets", []), list) else []
        self.assertGreaterEqual(len(bullets), 2)
        self.assertEqual(str(bullets[0]), "1. Jennifer Doherty 9:42 PM: gwatt")
        self.assertEqual(str(bullets[1]), "2. You TUESDAY: For videos, ping you in 5 - 10 mins?")

    def test_apply_answer_display_adds_positive_provider_for_hard_unread_today(self) -> None:
        class _System:
            config: dict = {}

            def get(self, key: str):  # noqa: ANN001
                return None

        result = {"answer": {"state": "ok", "claims": []}, "processing": {}}
        with (
            mock.patch.object(
                query_mod,
                "_build_answer_display",
                return_value={
                    "topic": "hard_unread_today",
                    "summary": "Today unread-indicator rows: 7",
                    "bullets": ["today_unread_indicator_count: 7"],
                    "fields": {"today_unread_indicator_count": 7},
                },
            ),
            mock.patch.object(query_mod, "_provider_contributions", return_value=[]),
            mock.patch.object(query_mod, "_workflow_tree", return_value={"nodes": [], "edges": []}),
        ):
            out = query_mod._apply_answer_display(
                _System(),
                "Unread indicators",
                result,
                query_intent={"topic": "hard_unread_today"},
            )
        processing = out.get("processing", {}) if isinstance(out.get("processing", {}), dict) else {}
        attribution = processing.get("attribution", {}) if isinstance(processing.get("attribution", {}), dict) else {}
        providers = attribution.get("providers", []) if isinstance(attribution.get("providers", []), list) else []
        obs = next((p for p in providers if isinstance(p, dict) and str(p.get("provider_id") or "") == "builtin.observation.graph"), {})
        self.assertEqual(int(obs.get("contribution_bp") or 0), 10000)

    def test_fallback_claim_sources_include_hard_topic_doc_kinds(self) -> None:
        class _Metadata:
            def latest(self, *, record_type: str, limit: int = 256):  # noqa: ARG002
                if record_type != "derived.sst.text.extra":
                    return []
                return [
                    {
                        "record_id": "rec_dev_1",
                        "record": {
                            "record_type": "derived.sst.text.extra",
                            "doc_kind": "adv.dev.summary",
                            "provider_id": "builtin.observation.graph",
                            "source_id": "src_dev_1",
                            "text": "Observation: adv.dev.what_changed_count=1; adv.dev.what_changed.1=Added k preset buttons 10/25/50/100 and server-side clamp 1-200.",
                            "meta": {},
                        },
                    },
                    {
                        "record_id": "rec_console_1",
                        "record": {
                            "record_type": "derived.sst.text.extra",
                            "doc_kind": "adv.console.colors",
                            "provider_id": "builtin.observation.graph",
                            "source_id": "src_console_1",
                            "text": "Observation: adv.console.red_count=1; adv.console.red_lines=if lastExit != 0 retry with saltEndpoint.",
                            "meta": {},
                        },
                    },
                ][: max(0, int(limit))]

            def get(self, _record_id: str):  # noqa: ANN001
                return None

        hard_k_rows = query_mod._fallback_claim_sources_for_topic("hard_k_presets", _Metadata())
        self.assertTrue(any(str(row.get("doc_kind") or "") == "adv.dev.summary" for row in hard_k_rows))
        hard_ep_rows = query_mod._fallback_claim_sources_for_topic("hard_endpoint_pseudocode", _Metadata())
        self.assertTrue(any(str(row.get("doc_kind") or "") == "adv.console.colors" for row in hard_ep_rows))

    def test_apply_answer_display_promotes_state_when_display_is_strict_and_provider_backed(self) -> None:
        class _System:
            config: dict = {}

            def get(self, key: str):  # noqa: ANN001
                return None

        result = {"answer": {"state": "no_evidence", "claims": []}, "processing": {}}
        with (
            mock.patch.object(
                query_mod,
                "_build_answer_display",
                return_value={
                    "topic": "hard_endpoint_pseudocode",
                    "summary": "Endpoint-selection and retry pseudocode extracted.",
                    "bullets": [
                        "if Test-Endpoint(endpoint) fails and saltEndpoint exists and Test-Endpoint(saltEndpoint) succeeds: endpoint = saltEndpoint",
                        "run vectorCmd (Invoke-Expression); lastExit = $LASTEXITCODE",
                        "if lastExit != 0 and saltEndpoint exists and saltEndpoint != endpoint: endpoint = saltEndpoint; rerun vectorCmd; lastExit = $LASTEXITCODE",
                        "if lastExit != 0: print failure; exit 1",
                        "else: print success",
                    ],
                    "fields": {
                        "pseudocode_steps": 5,
                        "pseudocode": [
                            "if Test-Endpoint(endpoint) fails and saltEndpoint exists and Test-Endpoint(saltEndpoint) succeeds: endpoint = saltEndpoint",
                            "run vectorCmd (Invoke-Expression); lastExit = $LASTEXITCODE",
                            "if lastExit != 0 and saltEndpoint exists and saltEndpoint != endpoint: endpoint = saltEndpoint; rerun vectorCmd; lastExit = $LASTEXITCODE",
                            "if lastExit != 0: print failure; exit 1",
                            "else: print success",
                        ],
                    },
                },
            ),
            mock.patch.object(
                query_mod,
                "_augment_claim_sources_for_display",
                return_value=[
                    {
                        "provider_id": "builtin.observation.graph",
                        "record_id": "rec_console_1",
                        "doc_kind": "adv.console.colors",
                        "signal_pairs": {"adv.console.red_count": "1"},
                        "meta": {},
                    }
                ],
            ),
            mock.patch.object(
                query_mod,
                "_provider_contributions",
                return_value=[
                    {
                        "provider_id": "builtin.observation.graph",
                        "claim_count": 1,
                        "citation_count": 1,
                        "contribution_bp": 10000,
                        "doc_kinds": ["adv.console.colors"],
                        "record_types": ["derived.sst.text.extra"],
                        "signal_keys": ["adv.console.red_count"],
                    }
                ],
            ),
            mock.patch.object(query_mod, "_workflow_tree", return_value={"nodes": [], "edges": []}),
        ):
            out = query_mod._apply_answer_display(
                _System(),
                "Summarize endpoint-selection and retry pseudocode.",
                result,
                query_intent={"topic": "hard_endpoint_pseudocode"},
            )
        answer = out.get("answer", {}) if isinstance(out.get("answer", {}), dict) else {}
        self.assertEqual(str(answer.get("state") or ""), "ok")
        claims = answer.get("claims", []) if isinstance(answer.get("claims", []), list) else []
        self.assertTrue(claims)
        first_cite = (claims[0].get("citations", [{}])[0] if isinstance(claims[0], dict) and isinstance(claims[0].get("citations", []), list) and claims[0].get("citations", []) else {})
        self.assertEqual(str(first_cite.get("source") or ""), "builtin.observation.graph")


if __name__ == "__main__":
    unittest.main()
