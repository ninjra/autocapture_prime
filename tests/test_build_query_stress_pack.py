from __future__ import annotations

import json
from pathlib import Path

from tools import build_query_stress_pack as mod


def test_build_pack_replays_when_target_exceeds_seed(tmp_path: Path) -> None:
    source = tmp_path / "cases.json"
    source.write_text(
        json.dumps(
            {
                "cases": [
                    {"id": "A", "query": "one"},
                    {"id": "B", "query": "two"},
                    {"id": "C", "question": "three"},
                ]
            }
        ),
        encoding="utf-8",
    )
    payload = mod.build_pack(sources=[source], target_count=8)
    cases = payload.get("cases", [])
    assert isinstance(cases, list)
    assert len(cases) == 8
    assert str(cases[0].get("id") or "") == "STRESS_001"
    assert str(cases[7].get("id") or "") == "STRESS_008"
    assert str(cases[0].get("query") or "") == "one"
    assert str(cases[3].get("query") or "") == "one"
    assert int(cases[3].get("replay_pass", 0) or 0) == 2
