from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from autocapture_nx.kernel import query as query_mod


class _MetaStore:
    def __init__(self, rows: dict[str, dict[str, object]]) -> None:
        self._rows = rows

    def get(self, record_id: str, default: object | None = None) -> dict[str, object] | object | None:
        return self._rows.get(str(record_id), default)

    def latest(self, record_type: str | None = None, *, limit: int = 10) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for record_id, row in self._rows.items():
            if not isinstance(row, dict):
                continue
            if record_type is not None and str(row.get("record_type") or "").strip() != str(record_type):
                continue
            out.append({"record_id": str(record_id), "record": row})
        out.reverse()
        return out[: max(1, int(limit))]


class QueryDisplayCitationFallbackTests(unittest.TestCase):
    def test_build_display_record_citation_uses_anchor_and_evidence_hash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            anchor_dir = data_dir / "anchor"
            anchor_dir.mkdir(parents=True, exist_ok=True)
            anchor_path = anchor_dir / "anchors.ndjson"
            anchor = {
                "record_type": "system.anchor",
                "schema_version": 1,
                "anchor_seq": 99,
                "ledger_head_hash": "abc123",
                "ts_utc": "2026-02-23T00:00:00Z",
            }
            anchor_path.write_text(json.dumps(anchor) + "\n", encoding="utf-8")
            (data_dir / "ledger.ndjson").write_text(
                json.dumps({"entry_hash": "abc123", "record_type": "test"}) + "\n",
                encoding="utf-8",
            )
            system = SimpleNamespace(
                config={
                    "storage": {
                        "data_dir": str(data_dir),
                        "anchor": {"path": str(anchor_path)},
                    }
                }
            )
            evidence_id = "run/evidence.capture.frame/1"
            metadata = _MetaStore(
                {
                    evidence_id: {
                        "record_type": "evidence.capture.frame",
                        "content_hash": "frame_hash_1",
                        "ts_utc": "2026-02-23T00:00:00Z",
                    }
                }
            )
            citation = query_mod._build_display_record_citation(  # noqa: SLF001
                system=system,
                metadata=metadata,
                result={},
                evidence_id=evidence_id,
                provider_id="builtin.observation.graph",
                claim_text="summary",
            )
            self.assertIsInstance(citation, dict)
            row = citation or {}
            self.assertEqual(str(row.get("evidence_id") or ""), evidence_id)
            self.assertEqual(str(row.get("evidence_hash") or ""), "frame_hash_1")
            self.assertEqual(str((row.get("locator") or {}).get("record_hash") or ""), "frame_hash_1")
            self.assertEqual(str(row.get("ledger_head") or ""), "abc123")
            self.assertEqual(int((row.get("anchor_ref") or {}).get("anchor_seq") or -1), 99)

    def test_add_display_backed_claim_populates_claims_when_sources_exist(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            anchor_dir = data_dir / "anchor"
            anchor_dir.mkdir(parents=True, exist_ok=True)
            anchor_path = anchor_dir / "anchors.ndjson"
            anchor = {
                "record_type": "system.anchor",
                "schema_version": 1,
                "anchor_seq": 1,
                "ledger_head_hash": "h001",
                "ts_utc": "2026-02-23T00:00:00Z",
            }
            anchor_path.write_text(json.dumps(anchor) + "\n", encoding="utf-8")
            (data_dir / "ledger.ndjson").write_text(
                json.dumps({"entry_hash": "h001", "record_type": "test"}) + "\n",
                encoding="utf-8",
            )
            evidence_id = "run/evidence.capture.frame/2"
            metadata = _MetaStore(
                {
                    evidence_id: {
                        "record_type": "evidence.capture.frame",
                        "content_hash": "frame_hash_2",
                    }
                }
            )
            system = SimpleNamespace(
                config={
                    "storage": {
                        "data_dir": str(data_dir),
                        "anchor": {"path": str(anchor_path)},
                    }
                },
                get=lambda name: metadata if name == "storage.metadata" else None,
            )
            answer_obj: dict[str, object] = {"state": "no_evidence", "claims": []}
            query_mod._add_display_backed_claim_if_needed(  # noqa: SLF001
                system=system,
                answer_obj=answer_obj,
                result={},
                display={"summary": "Detected focus on incident workspace."},
                display_sources=[{"record_id": evidence_id, "provider_id": "builtin.observation.graph"}],
            )
            claims = answer_obj.get("claims", [])
            self.assertTrue(isinstance(claims, list) and len(claims) == 1)
            citation = claims[0]["citations"][0]
            self.assertEqual(str(citation.get("evidence_id") or ""), evidence_id)
            self.assertEqual(str(citation.get("ledger_head") or ""), "h001")
            self.assertEqual(str(citation.get("evidence_hash") or ""), "frame_hash_2")

    def test_add_display_backed_claim_uses_result_evidence_when_sources_missing(self) -> None:
        evidence_id = "run/evidence.capture.frame/3"
        metadata = _MetaStore(
            {
                evidence_id: {
                    "record_type": "evidence.capture.frame",
                    "content_hash": "frame_hash_3",
                }
            }
        )
        system = SimpleNamespace(
            config={},
            get=lambda name: metadata if name == "storage.metadata" else None,
        )
        answer_obj: dict[str, object] = {"state": "no_evidence", "claims": []}
        result = {
            "answer": {
                "claims": [
                    {
                        "text": "seed",
                        "citations": [
                            {
                                "evidence_id": evidence_id,
                                "locator": {"record_id": evidence_id},
                            }
                        ],
                    }
                ]
            }
        }
        query_mod._add_display_backed_claim_if_needed(  # noqa: SLF001
            system=system,
            answer_obj=answer_obj,
            result=result,
            display={"summary": "Detected focus on incident workspace."},
            display_sources=[],
        )
        claims = answer_obj.get("claims", [])
        self.assertTrue(isinstance(claims, list) and len(claims) == 1)
        citation = claims[0]["citations"][0]
        self.assertEqual(str(citation.get("evidence_id") or ""), evidence_id)

    def test_add_display_backed_claim_falls_back_to_latest_citable_record(self) -> None:
        derived_id = "run/derived.sst.text.extra/42"
        metadata = _MetaStore(
            {
                derived_id: {
                    "record_type": "derived.sst.text.extra",
                    "content_hash": "derived_hash_42",
                    "text": "window_title: Focused Ticket Window",
                }
            }
        )
        system = SimpleNamespace(
            config={},
            get=lambda name: metadata if name == "storage.metadata" else None,
        )
        answer_obj: dict[str, object] = {"state": "no_evidence", "claims": []}
        query_mod._add_display_backed_claim_if_needed(  # noqa: SLF001
            system=system,
            answer_obj=answer_obj,
            result={},
            display={"summary": "Focused ticket window detected from metadata clues."},
            display_sources=[],
        )
        claims = answer_obj.get("claims", [])
        self.assertTrue(isinstance(claims, list) and len(claims) == 1)
        citation = claims[0]["citations"][0]
        self.assertEqual(str(citation.get("derived_id") or ""), derived_id)

    def test_add_display_backed_claim_skips_indeterminate_summary(self) -> None:
        evidence_id = "run/evidence.capture.frame/4"
        metadata = _MetaStore(
            {
                evidence_id: {
                    "record_type": "evidence.capture.frame",
                    "content_hash": "frame_hash_4",
                }
            }
        )
        system = SimpleNamespace(
            config={},
            get=lambda name: metadata if name == "storage.metadata" else None,
        )
        answer_obj: dict[str, object] = {"state": "no_evidence", "claims": []}
        query_mod._add_display_backed_claim_if_needed(  # noqa: SLF001
            system=system,
            answer_obj=answer_obj,
            result={},
            display={"summary": "Indeterminate: no verifiable evidence is available yet."},
            display_sources=[{"record_id": evidence_id, "provider_id": "builtin.observation.graph"}],
        )
        claims = answer_obj.get("claims", [])
        self.assertEqual(claims, [])

    def test_build_display_record_citation_accepts_allowed_derived_without_anchor(self) -> None:
        metadata = _MetaStore(
            {
                "run/derived.sst.text.extra/10": {
                    "record_type": "derived.sst.text.extra",
                    "content_hash": "derived_hash_10",
                    "text": "derived signal payload",
                }
            }
        )
        system = SimpleNamespace(config={})
        citation = query_mod._build_display_record_citation(  # noqa: SLF001
            system=system,
            metadata=metadata,
            result={},
            evidence_id="run/derived.sst.text.extra/10",
            provider_id="builtin.observation.graph",
            claim_text="structured summary",
        )
        self.assertIsInstance(citation, dict)
        row = citation or {}
        self.assertEqual(str(row.get("derived_id") or ""), "run/derived.sst.text.extra/10")
        self.assertEqual(str(row.get("derived_hash") or ""), "derived_hash_10")
        self.assertEqual(str(row.get("evidence_id") or ""), "")
        self.assertEqual(str((row.get("locator") or {}).get("record_id") or ""), "run/derived.sst.text.extra/10")

    def test_display_strict_state_advanced_heuristic_requires_meaningful_payload(self) -> None:
        display = {
            "summary": "Detected focused incident workspace with extracted details.",
            "bullets": [
                "incident_subject: Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476",
                "sender: Permian Resources Service Desk",
                "buttons: COMPLETE; VIEW DETAILS",
                "timeline_count: 2",
            ],
            "fields": {
                "incident_subject": "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476",
                "sender": "Permian Resources Service Desk",
            },
        }
        self.assertTrue(bool(query_mod._display_is_sufficient_for_strict_state("adv_incident", display)))  # noqa: SLF001

    def test_display_strict_state_adv_incident_accepts_complete_fields(self) -> None:
        display = {
            "summary": "Incident email: subject=Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476; sender=Permian Resources Service Desk; domain=permian.xyz.com",
            "bullets": ["action_buttons: COMPLETE, VIEW DETAILS"],
            "fields": {
                "subject": "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476",
                "sender_display": "Permian Resources Service Desk",
                "sender_domain": "permian.xyz.com",
                "action_buttons": "COMPLETE|VIEW DETAILS",
            },
        }
        self.assertTrue(bool(query_mod._display_is_sufficient_for_strict_state("adv_incident", display)))  # noqa: SLF001

    def test_display_strict_state_adv_incident_rejects_missing_primary_button(self) -> None:
        display = {
            "summary": "Incident email: subject=Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476; sender=Permian Resources Service Desk; domain=permian.xyz.com",
            "bullets": ["action_buttons: COMPLETE"],
            "fields": {
                "subject": "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476",
                "sender_display": "Permian Resources Service Desk",
                "sender_domain": "permian.xyz.com",
                "action_buttons": "COMPLETE",
            },
        }
        self.assertFalse(bool(query_mod._display_is_sufficient_for_strict_state("adv_incident", display)))  # noqa: SLF001

    def test_display_strict_state_hard_heuristic_rejects_indeterminate(self) -> None:
        display = {
            "summary": "Indeterminate: missing evidence.",
            "bullets": ["required_source: structured adv.* records for this topic"],
            "fields": {"elapsed_minutes": 2},
        }
        self.assertFalse(bool(query_mod._display_is_sufficient_for_strict_state("hard_time_to_assignment", display)))  # noqa: SLF001

    def test_allowed_claim_record_types_include_window_and_uia_evidence(self) -> None:
        self.assertTrue(bool(query_mod._is_allowed_claim_record_type("evidence.window.meta")))  # noqa: SLF001
        self.assertTrue(bool(query_mod._is_allowed_claim_record_type("evidence.uia.snapshot")))  # noqa: SLF001

    def test_display_strict_state_advanced_support_snippets_are_sufficient(self) -> None:
        display = {
            "summary": "Fallback extracted signals are available while structured advanced records are incomplete.",
            "bullets": [
                "required_source: structured adv.* records for this topic",
                "fallback_status: no structured advanced records available yet",
                "evidence: Slack | host window visible",
                "evidence: Remote Desktop Web Client | VDI window visible",
            ],
            "fields": {
                "required_doc_kind": "adv.window.inventory",
                "support_snippets": [
                    "Slack window visible",
                    "Remote Desktop Web Client visible",
                ],
                "support_snippet_count": 2,
            },
        }
        self.assertTrue(bool(query_mod._display_is_sufficient_for_strict_state("adv_window_inventory", display)))  # noqa: SLF001

    def test_display_strict_state_adv_calendar_accepts_metadata_fallback(self) -> None:
        display = {
            "summary": "Calendar: January 2026; selected date=not_visible",
            "bullets": [],
            "fields": {
                "month_year": "January 2026",
                "selected_date": "not_visible",
                "schedule_item_count": "0",
            },
        }
        self.assertTrue(bool(query_mod._display_is_sufficient_for_strict_state("adv_calendar", display)))  # noqa: SLF001

    def test_display_strict_state_generic_accepts_evidence_clues(self) -> None:
        display = {
            "summary": "window_title: Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476",
            "bullets": ["evidence: window_process: msedge.exe"],
            "fields": {"metadata_clue_count": "3"},
        }
        self.assertTrue(bool(query_mod._display_is_sufficient_for_strict_state("generic", display)))  # noqa: SLF001

    def test_metadata_window_clues_extracts_window_and_uia_rows(self) -> None:
        metadata = _MetaStore(
            {
                "run/evidence.window.meta/1": {
                    "record_type": "evidence.window.meta",
                    "window": {"title": "Focused Ticket Window", "process_path": "C:/Program Files/App/app.exe", "pid": 1234},
                },
                "run/evidence.uia.snapshot/1": {
                    "record_type": "evidence.uia.snapshot",
                    "window": {"title": "UIA Focused Window", "process_path": "C:/Program Files/App/uia.exe", "pid": 4321},
                    "focus_path": [{"role": "button", "name": "View Details"}],
                },
            }
        )
        rows = query_mod._metadata_window_clues(metadata, limit=8)  # noqa: SLF001
        self.assertTrue(any("window_title: Focused Ticket Window" in row for row in rows))
        self.assertTrue(any("uia_window_title:" in row or "uia_focus:" in row for row in rows))


if __name__ == "__main__":
    unittest.main()
