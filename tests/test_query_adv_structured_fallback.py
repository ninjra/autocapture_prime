from __future__ import annotations

from autocapture_nx.kernel import query as query_mod


def test_iter_adv_sources_accepts_ocr_structured_rows() -> None:
    src = {
        "record_id": "rid.focus.1",
        "provider_id": "builtin.observation.graph",
        "doc_kind": "adv.focus.window",
        "signal_pairs": {
            "adv.focus.window": "Task Set Up Open Invoice",
            "adv.focus.evidence_1_kind": "selected_row",
            "adv.focus.evidence_1_text": "Task Set Up Open Invoice for Contractor Ricardo Lopez",
        },
        "meta": {
            "source_modality": "ocr",
            "source_state_id": "pending",
            "source_backend": "heuristic",
        },
    }
    picks = query_mod._iter_adv_sources([src], "adv_focus")
    assert len(picks) == 1
    assert str(picks[0].get("record_id") or "") == "rid.focus.1"


def test_has_structured_adv_source_accepts_ocr_structured_rows() -> None:
    src = {
        "record_id": "rid.details.1",
        "provider_id": "builtin.observation.graph",
        "doc_kind": "adv.details.kv",
        "signal_pairs": {
            "adv.details.1.label": "Opened at",
            "adv.details.1.value": "Feb 02, 2026 - 12:08pm CST",
            "adv.details.2.label": "Service requestor",
            "adv.details.2.value": "Norry Mata",
        },
        "meta": {
            "source_modality": "ocr",
            "source_state_id": "pending",
            "source_backend": "heuristic",
        },
    }
    assert query_mod._has_structured_adv_source("adv_details", [src]) is True


def test_adv_fallback_message_is_not_vlm_only() -> None:
    display = query_mod._build_answer_display(
        "Which window has focus?",
        [],
        [],
        query_intent={"topic": "adv_focus"},
    )
    summary = str(display.get("summary") or "")
    bullets = [str(x or "") for x in (display.get("bullets") or [])]
    fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
    assert "VLM-grounded" not in summary
    assert any("required_source: structured adv.* records for this topic" == b for b in bullets)
    assert str(fields.get("required_doc_kind") or "") == "adv.focus.window"
