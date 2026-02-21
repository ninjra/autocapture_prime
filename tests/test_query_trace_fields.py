from __future__ import annotations

import unittest
from unittest import mock

from autocapture_nx.kernel import query as query_mod


class _Parser:
    def parse(self, _text: str):
        return {"time_window": None}


class _Retrieval:
    def __init__(self, results):
        self._results = list(results)

    def search(self, _text: str, *, time_window=None):
        _ = time_window
        return list(self._results)

    def trace(self):
        return []


class _Answer:
    def build(self, claims):
        return {"state": "ok", "claims": claims, "errors": []}


class _EventBuilder:
    run_id = "run_test"

    def ledger_entry(self, *_args, **_kwargs):
        return "ledger_head_test"

    def last_anchor(self):
        return "anchor_ref_test"


class _Meta:
    def __init__(self, mapping):
        self._m = dict(mapping)

    def get(self, key, default=None):
        return self._m.get(key, default)

    def keys(self):
        return list(self._m.keys())


class _System:
    def __init__(self, config, caps):
        self.config = config
        self._caps = dict(caps)

    def get(self, name):
        return self._caps[name]


class QueryTraceFieldsTests(unittest.TestCase):
    def test_run_query_writes_query_trace_and_metrics(self) -> None:
        evidence_id = "run_test/evidence.capture.segment/seg1"
        derived_id = "run_test/derived.text.ocr/provider/seg1"
        metadata = _Meta(
            {
                evidence_id: {
                    "record_type": "evidence.capture.segment",
                    "content_hash": "hash_e",
                    "ts_utc": "2026-02-07T00:00:00Z",
                },
                derived_id: {
                    "record_type": "derived.text.ocr",
                    "text": "Inbox count is 4",
                    "span_ref": {"kind": "text", "note": "test"},
                    "content_hash": "hash_d",
                },
            }
        )
        system = _System(
            config={
                "runtime": {"run_id": "run_test"},
                "storage": {"data_dir": "/tmp/data"},
                "processing": {
                    "state_layer": {"query_enabled": False},
                    "on_query": {"allow_decode_extract": False},
                },
                "plugins": {"locks": {"lockfile": "config/plugin_locks.json"}},
            },
            caps={
                "time.intent_parser": _Parser(),
                "retrieval.strategy": _Retrieval([{"record_id": evidence_id, "derived_id": derived_id, "ts_utc": "2026-02-07T00:00:00Z"}]),
                "answer.builder": _Answer(),
                "storage.metadata": metadata,
                "event.builder": _EventBuilder(),
            },
        )
        with mock.patch.object(query_mod, "append_fact_line") as append_mock:
            out = query_mod.run_query(system, "how many inboxes do i have open")

        processing = out.get("processing", {})
        self.assertIsInstance(processing, dict)
        trace = processing.get("query_trace", {})
        self.assertIsInstance(trace, dict)
        self.assertTrue(str(trace.get("query_run_id", "")).startswith("qry_"))
        self.assertEqual(str(trace.get("method")), "classic")
        stage_ms = trace.get("stage_ms", {})
        self.assertIsInstance(stage_ms, dict)
        self.assertGreaterEqual(float(stage_ms.get("classic_query", 0.0)), 0.0)
        self.assertGreaterEqual(float(stage_ms.get("display", 0.0)), 0.0)
        self.assertGreater(float(stage_ms.get("total", 0.0)), 0.0)
        handoffs = trace.get("handoffs", [])
        self.assertIsInstance(handoffs, list)
        self.assertGreaterEqual(len(handoffs), 2)
        rel_paths = [str(call.kwargs.get("rel_path", "")) for call in append_mock.call_args_list]
        self.assertIn("query_eval.ndjson", rel_paths)
        self.assertIn("query_trace.ndjson", rel_paths)

    def test_query_trace_carries_promptops_fields(self) -> None:
        evidence_id = "run_test/evidence.capture.segment/seg1"
        derived_id = "run_test/derived.text.ocr/provider/seg1"
        metadata = _Meta(
            {
                evidence_id: {
                    "record_type": "evidence.capture.segment",
                    "content_hash": "hash_e",
                    "ts_utc": "2026-02-07T00:00:00Z",
                },
                derived_id: {
                    "record_type": "derived.text.ocr",
                    "text": "Inbox count is 4",
                    "span_ref": {"kind": "text", "note": "test"},
                    "content_hash": "hash_d",
                },
            }
        )
        system = _System(
            config={
                "runtime": {"run_id": "run_test"},
                "storage": {"data_dir": "/tmp/data"},
                "processing": {
                    "state_layer": {"query_enabled": False},
                    "on_query": {"allow_decode_extract": False},
                },
                "plugins": {"locks": {"lockfile": "config/plugin_locks.json"}},
                "promptops": {
                    "enabled": True,
                    "mode": "auto_apply",
                    "query_strategy": "normalize_query",
                    "model_strategy": "model_contract",
                    "require_citations": True,
                    "history": {"enabled": False},
                    "github": {"enabled": False},
                    "sources": [],
                    "examples": {},
                    "metrics": {"enabled": False},
                    "review": {"enabled": False},
                },
            },
            caps={
                "time.intent_parser": _Parser(),
                "retrieval.strategy": _Retrieval([{"record_id": evidence_id, "derived_id": derived_id, "ts_utc": "2026-02-07T00:00:00Z"}]),
                "answer.builder": _Answer(),
                "storage.metadata": metadata,
                "event.builder": _EventBuilder(),
            },
        )
        out = query_mod.run_query(system, "pls help w/ query")
        processing = out.get("processing", {}) if isinstance(out.get("processing", {}), dict) else {}
        trace = processing.get("query_trace", {}) if isinstance(processing.get("query_trace", {}), dict) else {}
        self.assertTrue(bool(trace.get("promptops_used", False)))
        self.assertEqual(str(trace.get("promptops_strategy") or ""), "normalize_query")
        self.assertEqual(str(trace.get("query_original") or ""), "pls help w/ query")
        self.assertTrue(bool(str(trace.get("query_effective") or "").strip()))
        self.assertIn("promptops_applied", trace)

    def test_apply_display_promotes_display_fields_when_hard_only_answer_text(self) -> None:
        system = _System(
            config={"runtime": {"run_id": "run_test"}},
            caps={"storage.metadata": _Meta({})},
        )
        base_result = {
            "answer": {"state": "ok", "claims": [], "errors": []},
            "processing": {"query_trace": {"winner": "classic", "method": "classic"}},
        }
        display = {
            "schema_version": 1,
            "summary": "Focused window: Outlook VDI",
            "bullets": ["evidence_1: Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476"],
            "fields": {"focus_window": "Outlook VDI", "evidence_count": "2"},
            "topic": "adv_focus",
        }
        with mock.patch.object(query_mod, "_hard_vlm_extract", return_value={"answer_text": "not_json"}), mock.patch.object(
            query_mod, "_build_answer_display", return_value=display
        ):
            out = query_mod._apply_answer_display(
                system,
                "Which window has keyboard focus?",
                base_result,
                query_intent={"topic": "adv_focus"},
            )
        processing = out.get("processing", {}) if isinstance(out.get("processing"), dict) else {}
        hard = processing.get("hard_vlm", {}) if isinstance(processing.get("hard_vlm"), dict) else {}
        fields = hard.get("fields", {}) if isinstance(hard.get("fields"), dict) else {}
        self.assertEqual(str(fields.get("focus_window") or ""), "Outlook VDI")
        self.assertEqual(str(fields.get("evidence_count") or ""), "2")

    def test_latest_evidence_record_id_falls_back_from_metadata(self) -> None:
        system = _System(
            config={},
            caps={
                "storage.metadata": _Meta(
                    {
                        "run_a/evidence.capture.frame/0": {
                            "record_type": "evidence.capture.frame",
                            "ts_utc": "2026-02-16T07:00:00Z",
                        },
                        "run_b/evidence.capture.frame/0": {
                            "record_type": "evidence.capture.frame",
                            "ts_utc": "2026-02-16T07:05:00Z",
                        },
                        "run_c/evidence.capture.segment/0": {
                            "record_type": "evidence.capture.segment",
                            "ts_utc": "2026-02-16T07:06:00Z",
                        },
                        "run_b/derived.text.ocr/x": {
                            "record_type": "derived.text.ocr",
                            "ts_utc": "2026-02-16T07:05:01Z",
                        },
                    }
                )
            },
        )
        rid = query_mod._latest_evidence_record_id(system)
        self.assertEqual(rid, "run_b/evidence.capture.frame/0")

    def test_apply_display_skips_hard_vlm_when_structured_adv_source_present_in_fallback_mode(self) -> None:
        system = _System(
            config={"runtime": {"run_id": "run_test"}, "processing": {"on_query": {"adv_hard_vlm_mode": "fallback"}}},
            caps={"storage.metadata": _Meta({})},
        )
        base_result = {
            "answer": {"state": "ok", "claims": [], "errors": []},
            "processing": {"query_trace": {"winner": "classic", "method": "classic"}},
        }
        claim_source = {
            "provider_id": "builtin.observation.graph",
            "doc_kind": "adv.calendar.schedule",
            "signal_pairs": {"adv.calendar.item_count": "5", "adv.calendar.month_year": "January 2026"},
            "meta": {"source_modality": "vlm", "source_state_id": "vlm"},
        }
        display = {
            "schema_version": 1,
            "summary": "Calendar: January 2026; selected_date=2",
            "bullets": [],
            "fields": {"schedule_item_count": "5"},
            "topic": "adv_calendar",
        }
        with (
            mock.patch.object(query_mod, "_claim_sources", return_value=[claim_source]),
            mock.patch.object(query_mod, "_claim_texts", return_value=[]),
            mock.patch.object(query_mod, "_build_answer_display", return_value=display),
            mock.patch.object(query_mod, "_hard_vlm_extract") as hard_mock,
        ):
            out = query_mod._apply_answer_display(
                system,
                "In the VDI right-side calendar pane extract month and items.",
                base_result,
                query_intent={"topic": "adv_calendar"},
            )
        self.assertFalse(hard_mock.called)
        answer = out.get("answer", {}) if isinstance(out.get("answer"), dict) else {}
        self.assertEqual(str(answer.get("summary") or ""), "Calendar: January 2026; selected_date=2")

    def test_apply_display_runs_hard_vlm_for_structured_adv_source_in_always_mode(self) -> None:
        system = _System(
            config={"runtime": {"run_id": "run_test"}},
            caps={"storage.metadata": _Meta({})},
        )
        base_result = {
            "answer": {"state": "ok", "claims": [], "errors": []},
            "processing": {"query_trace": {"winner": "classic", "method": "classic"}},
        }
        claim_source = {
            "provider_id": "builtin.observation.graph",
            "doc_kind": "adv.calendar.schedule",
            "signal_pairs": {"adv.calendar.item_count": "5", "adv.calendar.month_year": "January 2026"},
            "meta": {"source_modality": "vlm", "source_state_id": "vlm"},
        }
        display = {
            "schema_version": 1,
            "summary": "Calendar: January 2026; selected_date=2",
            "bullets": [],
            "fields": {"schedule_item_count": "5"},
            "topic": "adv_calendar",
        }
        with (
            mock.patch.object(query_mod, "_claim_sources", return_value=[claim_source]),
            mock.patch.object(query_mod, "_claim_texts", return_value=[]),
            mock.patch.object(query_mod, "_build_answer_display", return_value=display),
            mock.patch.object(query_mod, "_hard_vlm_extract", return_value={"month_year": "January 2026"}) as hard_mock,
        ):
            out = query_mod._apply_answer_display(
                system,
                "In the VDI right-side calendar pane extract month and items.",
                base_result,
                query_intent={"topic": "adv_calendar"},
            )
        self.assertTrue(hard_mock.called)
        answer = out.get("answer", {}) if isinstance(out.get("answer"), dict) else {}
        self.assertEqual(str(answer.get("summary") or ""), "Calendar: January 2026; selected_date=2")


if __name__ == "__main__":
    unittest.main()
