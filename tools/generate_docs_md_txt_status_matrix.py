from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
MATRIX_PATH = REPO_ROOT / "docs/reports/docs_md_txt_status_matrix.md"
AUDIT_PATH = REPO_ROOT / "docs/reports/docs_deprecation_audit_2026-02-18.md"

AUTHORITATIVE_PATHS = {
    "docs/AutocapturePrime_4Pillars_Upgrade_Plan.md",
    "docs/autocapture_prime.md",
    "docs/autocapture_prime_codex_implementation.md",
    "docs/autocapture_prime_testquestions2.txt",
    "docs/blueprints/feature_completeness_blueprint.txt",
    "docs/promptops_contract.md",
    "docs/windows-sidecar-capture-interface.md",
    "docs/windows-hypervisor-popup-query-contract.md",
}

MOVED_THIS_PASS = {
    "plans": [
        "docs/deprecated/plans/codex-work-order-autocapture-prime-memory-plan.md",
        "docs/deprecated/plans/core-hardening-recommendations-plan.md",
        "docs/deprecated/plans/golden-soak-closure-plan.md",
        "docs/deprecated/plans/promptops-autonomous-self-optimization-plan.md",
        "docs/deprecated/plans/repo-4-pillars-pure-function-optimization-plan.md",
    ],
    "txt": [
        "docs/deprecated/reports/baseline_repo_state.txt",
        "docs/deprecated/reports/grep_anchor.txt",
        "docs/deprecated/reports/grep_canonical_json.txt",
        "docs/deprecated/reports/grep_capture_pipeline.txt",
        "docs/deprecated/reports/grep_citation.txt",
        "docs/deprecated/reports/grep_derived.txt",
        "docs/deprecated/reports/grep_dpapi.txt",
        "docs/deprecated/reports/grep_evidence.txt",
        "docs/deprecated/reports/grep_fastapi.txt",
        "docs/deprecated/reports/grep_job_object.txt",
        "docs/deprecated/reports/grep_journal.txt",
        "docs/deprecated/reports/grep_ledger.txt",
        "docs/deprecated/reports/grep_network_policy.txt",
        "docs/deprecated/reports/grep_plugin_manifest.txt",
        "docs/deprecated/reports/grep_proof_bundle.txt",
        "docs/deprecated/reports/grep_replay.txt",
        "docs/deprecated/reports/grep_run_id.txt",
        "docs/deprecated/reports/grep_scheduler_governor.txt",
        "docs/deprecated/reports/grep_sqlcipher.txt",
        "docs/deprecated/reports/grep_subprocess_plugin.txt",
        "docs/deprecated/reports/grep_websocket.txt",
    ],
}


@dataclass(frozen=True)
class Row:
    path: str
    status: str
    outstanding: str
    action: str
    rationale: str


def _classify(rel: str) -> Row:
    if rel.startswith("docs/deprecated/"):
        return Row(
            path=rel,
            status="deprecated",
            outstanding="N",
            action="archived",
            rationale="Previously completed or superseded artifact.",
        )
    if rel.startswith("docs/plans/") and rel != "docs/plans/README.md":
        return Row(
            path=rel,
            status="active-plan",
            outstanding="Y",
            action="keep_active",
            rationale="Active outstanding planning document.",
        )
    if rel in AUTHORITATIVE_PATHS:
        return Row(
            path=rel,
            status="active-authoritative",
            outstanding="N",
            action="keep_active",
            rationale="Authoritative contract or specification source.",
        )
    if rel.startswith("docs/reports/"):
        return Row(
            path=rel,
            status="active-report",
            outstanding="N",
            action="keep_active",
            rationale="Generated report or operational summary artifact.",
        )
    if rel.startswith(("docs/adr/", "docs/spec/", "docs/specs/", "docs/blueprints/")):
        return Row(
            path=rel,
            status="active-spec",
            outstanding="N",
            action="keep_active",
            rationale="Architecture or specification reference.",
        )
    if rel.startswith("docs/handoffs/"):
        return Row(
            path=rel,
            status="active-handoff",
            outstanding="N",
            action="keep_active",
            rationale="Cross-repo handoff contract artifact.",
        )
    if rel.startswith("docs/runbooks/") or rel == "docs/runbook.md":
        return Row(
            path=rel,
            status="active-runbook",
            outstanding="N",
            action="keep_active",
            rationale="Runbook for operations or release procedures.",
        )
    return Row(
        path=rel,
        status="active-reference",
        outstanding="N",
        action="keep_active",
        rationale="Reference documentation.",
    )


def _collect_rows() -> list[Row]:
    files = sorted(
        path
        for path in DOCS_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in {".md", ".txt"}
    )
    return [_classify(path.relative_to(REPO_ROOT).as_posix()) for path in files]


def _render_matrix(rows: list[Row]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1

    lines: list[str] = []
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines.append("# Docs MD/TXT Status Matrix")
    lines.append("")
    lines.append(f"Generated: {timestamp}")
    lines.append("")
    lines.append("Scope: every `docs/**/*.md` and `docs/**/*.txt` file.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for key in sorted(counts):
        lines.append(f"- `{key}`: {counts[key]}")
    lines.append("")
    lines.append("| Path | Status | Outstanding | Action | Rationale |")
    lines.append("| --- | --- | --- | --- | --- |")
    for row in rows:
        lines.append(
            f"| `{row.path}` | `{row.status}` | `{row.outstanding}` | "
            f"`{row.action}` | {row.rationale} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_audit() -> str:
    lines: list[str] = []
    lines.append("# Docs Deprecation Audit (2026-02-18)")
    lines.append("")
    lines.append("## Scope")
    lines.append("- Re-checked every markdown/text file under `docs/`.")
    lines.append("- Deprecated non-outstanding active plans and stale report text artifacts.")
    lines.append("- Regenerated full docs md/txt status matrix with per-file rows.")
    lines.append("")
    lines.append("## Deprecated This Pass")
    lines.append("")
    lines.append("Moved to `docs/deprecated/plans/`:")
    for path in MOVED_THIS_PASS["plans"]:
        lines.append(f"- `{path}`")
    lines.append("")
    lines.append("Moved to `docs/deprecated/reports/`:")
    for path in MOVED_THIS_PASS["txt"]:
        lines.append(f"- `{path}`")
    lines.append("")
    lines.append("## Active Outstanding Plans")
    lines.append("- None under `docs/plans/` (index only).")
    lines.append("")
    lines.append("## Matrix Update")
    lines.append("- Added/updated: `docs/reports/docs_md_txt_status_matrix.md`.")
    lines.append("- Linked from: `docs/reports/implementation_matrix.md`.")
    lines.append("")
    lines.append("## Result")
    lines.append("- Deprecation and status are explicit for every docs md/txt artifact.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    rows = _collect_rows()
    MATRIX_PATH.write_text(_render_matrix(rows), encoding="utf-8")
    AUDIT_PATH.write_text(_render_audit(), encoding="utf-8")
    print(f"wrote {MATRIX_PATH.relative_to(REPO_ROOT)} ({len(rows)} rows)")
    print(f"wrote {AUDIT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
