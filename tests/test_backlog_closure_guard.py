from __future__ import annotations

from pathlib import Path


def test_promptops_plan_checklist_has_no_open_backlog_rows() -> None:
    path = Path("docs/plans/promptops-four-pillars-improvement-plan.md")
    text = path.read_text(encoding="utf-8")
    tracked_lines = [
        "Baseline report generated for PromptOps latency, success/failure rates, and citation coverage.",
        "PromptOps flow emits per-step timings and decision-state metrics.",
        "Golden eval harness persists immutable baseline snapshot for regression diffs.",
        "Prompt bundle and plugin registry are cached safely and reused.",
        "Query p50/p95 latency improvement is measurable versus sprint-1 baseline.",
        "No correctness regressions in golden eval set.",
        "PromptOps strategy path is explicit per answer.",
        "Each answer includes claim-to-evidence links or explicit indeterminate labels.",
        "Golden Q/H tests show improved correctness without tactical query-specific logic.",
        "External endpoint policy is enforced fail-closed (localhost-only unless explicit policy override).",
        "Prompt history/metrics redaction policy is explicit and test-backed.",
        "Audit chain can reconstruct who/what/when for each prompt mutation and review decision.",
        "Golden profile executes all required plugins in the intended order.",
        "Q and H suites run in one command and emit confidence + contribution matrix.",
        "Roll-forward and rollback playbooks are documented and tested.",
        "`screen.parse.v1`, `screen.index.v1`, and `screen.answer.v1` contract tasks are explicitly represented in implementation matrix with verification hooks.",
        "UI graph/provenance schemas are versioned and validated in CI.",
        "Plugin allowlist and safe-mode startup checks gate PromptOps-affecting changes.",
    ]
    for snippet in tracked_lines:
        open_marker = f"- [ ] {snippet}"
        assert open_marker not in text


def test_codex_implementation_matrix_dod_row_not_partial() -> None:
    path = Path("docs/reports/autocapture_prime_codex_implementation_matrix.md")
    text = path.read_text(encoding="utf-8")
    assert "| 6. Definition of done gates | partial |" not in text

