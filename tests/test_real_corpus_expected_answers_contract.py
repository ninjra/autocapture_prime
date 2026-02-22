from __future__ import annotations

import json
from pathlib import Path


def test_real_corpus_contract_shape_and_counts() -> None:
    path = Path("docs/contracts/real_corpus_expected_answers_v1.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload.get("schema") == "autocapture.real_corpus_expected_answers.v1"
    strict = payload.get("strict", {})
    assert isinstance(strict, dict)
    cases = strict.get("cases", [])
    assert isinstance(cases, list)
    ids = [str(item.get("id") or "") for item in cases if isinstance(item, dict)]
    assert len(ids) == 20
    assert len(set(ids)) == len(ids)
    expected_total = int(strict.get("expected_total", 0) or 0)
    assert expected_total == len(ids)
    assert all(case_id.startswith(("Q", "H")) for case_id in ids)
    source_policy = strict.get("source_policy", {})
    assert isinstance(source_policy, dict)
    assert source_policy.get("require_real_corpus") is True
    disallowed = source_policy.get("disallowed_substrings", [])
    assert isinstance(disallowed, list) and len(disallowed) > 0
    assert payload.get("generic_policy", {}).get("blocking") is False
