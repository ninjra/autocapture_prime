from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_under_hypervisor_doc_has_no_unresolved_placeholders() -> None:
    text = _read("docs/autocapture_prime_UNDER_HYPERVISOR.md")
    assert "<AP_ENTRYPOINT>" not in text
    assert "## Open items to fill in" not in text
    assert "## Resolved contract values" in text


def test_required_contract_artifacts_exist() -> None:
    required = (
        "docs/_codex_repo_manifest.txt",
        "docs/_codex_repo_review.md",
        "docs/schemas/ui_graph.schema.json",
        "docs/schemas/provenance.schema.json",
        "tests/golden/questions.yaml",
        "tests/golden/expected.yaml",
    )
    for rel in required:
        path = REPO_ROOT / rel
        assert path.exists(), rel
        assert path.read_text(encoding="utf-8").strip(), rel


def test_contract_schemas_parse_and_have_required_keys() -> None:
    ui_graph = json.loads(_read("docs/schemas/ui_graph.schema.json"))
    provenance = json.loads(_read("docs/schemas/provenance.schema.json"))
    assert "required" in ui_graph
    assert "nodes" in ui_graph.get("required", [])
    assert "$defs" in provenance
    evidence = provenance["$defs"].get("evidence_object", {})
    assert "required" in evidence
    assert {"evidence_id", "type", "source", "hash"}.issubset(set(evidence["required"]))


def test_golden_files_have_expected_markers() -> None:
    questions = _read("tests/golden/questions.yaml")
    expected = _read("tests/golden/expected.yaml")
    assert "cases:" in questions
    assert "id: QG-001" in questions
    assert "question:" in questions
    assert "cases:" in expected
    assert "required_evidence_refs:" in expected
    assert "hash" in expected
