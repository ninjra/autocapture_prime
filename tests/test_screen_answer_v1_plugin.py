from __future__ import annotations

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.screen_answer_v1.plugin import ScreenAnswerPlugin


def _ctx() -> PluginContext:
    return PluginContext(config={}, get_capability=lambda _n: None, logger=lambda _m: None)


def test_screen_answer_returns_cited_claims() -> None:
    plugin = ScreenAnswerPlugin("builtin.screen.answer.v1", _ctx())
    indexed = {
        "chunks": [
            {
                "chunk_id": "c1",
                "node_id": "n1",
                "text": "Outlook Open Invoice for Contractor Ricardo Lopez",
                "terms": ["outlook", "open", "invoice", "contractor", "ricardo", "lopez"],
                "evidence_id": "evidence_c1",
            }
        ],
        "evidence": [
            {
                "evidence_id": "evidence_c1",
                "hash": "a" * 64,
                "source": {"frame_id": "frame_1", "node_id": "n1"},
                "bbox": [10, 10, 500, 500],
            }
        ],
    }
    out = plugin.answer("who is the contractor on open invoice", indexed)
    assert out["state"] == "ok"
    assert out["claims"]
    assert out["claims"][0]["citations"][0]["evidence_id"] == "evidence_c1"


def test_screen_answer_no_evidence_for_unmatched_query() -> None:
    plugin = ScreenAnswerPlugin("builtin.screen.answer.v1", _ctx())
    out = plugin.answer("nonexistent token set", {"chunks": [], "evidence": []})
    assert out["state"] == "no_evidence"
    assert out["claims"] == []
