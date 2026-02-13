#!/usr/bin/env python3
"""Generate an exhaustive remaining-work matrix from full_repo_miss_inventory output."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


AUTH_DOC_PREFIXES = (
    "docs/blueprints/",
    "docs/spec/",
    "docs/specs/",
)
SPECIAL_AUTH_DOCS = {
    "AGENTS.md",
    "docs/AutocapturePrime_4Pillars_Upgrade_Plan.md",
    "docs/windows-sidecar-capture-interface.md",
}

FOUR_PILLARS_REF_EXCLUDE_PREFIXES = (
    "docs/AutocapturePrime_4Pillars_Upgrade_Plan.md:",
    "docs/reports/implementation_matrix_remaining_2026-02-12.md:",
    "docs/reports/full_repo_miss_inventory_2026-02-12.md:",
    "incomplete-items-matrix-plan.md:",
)


@dataclass(frozen=True)
class FourPillarsItem:
    item_id: str
    line: int
    title: str
    external_refs: int
    ref_examples: tuple[str, ...]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_auth_doc(source_path: str) -> bool:
    if source_path in SPECIAL_AUTH_DOCS:
        return True
    return source_path.startswith(AUTH_DOC_PREFIXES)


def _bucket_for_source(source_path: str) -> str:
    if _is_auth_doc(source_path):
        return "authoritative_doc"
    if source_path.startswith("docs/reports/"):
        return "derived_report"
    if source_path.startswith("artifacts/"):
        return "generated_artifact"
    if source_path.startswith("docs/"):
        return "other_doc"
    return "code_or_tooling"


def _quote_cell(text: str) -> str:
    return text.replace("|", "\\|")


def _parse_four_pillars_items(repo_root: Path, rel_path: str) -> list[FourPillarsItem]:
    path = repo_root / rel_path
    if not path.exists():
        return []
    out: list[FourPillarsItem] = []
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.rstrip()
        if line.startswith("### A") and ") " in line:
            item_id = line.split(") ", 1)[0].replace("### ", "").strip()
            title = line.split(") ", 1)[1].strip()
            pattern = rf"\b{item_id}\)"
            refs = _search_refs(repo_root, pattern)
            out.append(
                FourPillarsItem(
                    item_id=item_id,
                    line=idx,
                    title=title,
                    external_refs=len(refs),
                    ref_examples=tuple(refs[:3]),
                )
            )
        if line.startswith("### Task A-"):
            head = line.replace("### Task ", "", 1)
            item_id = head.split(":", 1)[0].strip()
            title = head.split(":", 1)[1].strip() if ":" in head else ""
            pattern = rf"\b{item_id}\b"
            refs = _search_refs(repo_root, pattern)
            out.append(
                FourPillarsItem(
                    item_id=item_id,
                    line=idx,
                    title=title,
                    external_refs=len(refs),
                    ref_examples=tuple(refs[:3]),
                )
            )
    return out


def _search_refs(repo_root: Path, pattern: str) -> list[str]:
    proc = subprocess.run(
        ["rg", "-n", "-e", pattern, "--hidden", "--glob", "!.git/*"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    refs: list[str] = []
    for line in (proc.stdout or "").splitlines():
        if any(line.startswith(prefix) for prefix in FOUR_PILLARS_REF_EXCLUDE_PREFIXES):
            continue
        if line.strip():
            refs.append(line.strip())
    return refs


def _render_markdown(
    *,
    inv: dict,
    rows: list[dict],
    sources: list[tuple[str, int]],
    source_breakdown: dict[str, dict[str, int]],
    four_pillars: list[FourPillarsItem],
) -> str:
    summary = inv.get("summary", {})
    now = datetime.now(timezone.utc).isoformat()
    categories = summary.get("categories", {})
    ids = Counter(r.get("item_id", "") for r in rows if str(r.get("item_id", "")).strip())
    auth_rows = [r for r in rows if _is_auth_doc(str(r.get("source_path", "")))]
    auth_ids = Counter(r.get("item_id", "") for r in auth_rows if str(r.get("item_id", "")).strip())
    bucket_counts = Counter(
        str(r.get("source_class", "")).strip() or _bucket_for_source(str(r.get("source_path", "")))
        for r in rows
    )
    code_placeholder_rows = [r for r in rows if r.get("category") == "code_todo_placeholder"]
    code_by_file = Counter(str(r.get("source_path", "")) for r in code_placeholder_rows)
    gate_failures = inv.get("gate_failures", [])

    lines: list[str] = []
    lines.append("# Implementation Matrix: Remaining Work (Full Repo Exhaustive, 2026-02-12)")
    lines.append("")
    lines.append("## Scope")
    lines.append(
        "This matrix is generated from the full-repo miss inventory and represents every currently detected miss marker across all scanned files."
    )
    lines.append("")
    lines.append("## Scan Metadata")
    lines.append(f"- Generated (matrix): `{now}`")
    lines.append(f"- Inventory generated: `{summary.get('generated_utc', '')}`")
    lines.append(f"- Scanned files: `{summary.get('scanned_files', 0)}`")
    lines.append(f"- Miss rows: `{summary.get('rows_total', 0)}`")
    lines.append(f"- Gate failures: `{summary.get('gate_failures_total', 0)}`")
    lines.append("")
    lines.append("## Canonical Full List")
    lines.append("- Full row-by-row list: `docs/reports/full_repo_miss_inventory_2026-02-12.md`")
    lines.append("- Raw machine-readable list: `artifacts/repo_miss_inventory/latest.json`")
    lines.append("")
    lines.append("## Category Counts")
    lines.append("| Category | Count |")
    lines.append("| --- | ---: |")
    for cat, count in sorted(categories.items(), key=lambda kv: (-int(kv[1]), kv[0])):
        lines.append(f"| `{cat}` | {int(count)} |")
    lines.append("")
    lines.append("## Source Bucket Counts")
    lines.append("| Bucket | Count |")
    lines.append("| --- | ---: |")
    for bucket, count in sorted(bucket_counts.items(), key=lambda kv: (-int(kv[1]), kv[0])):
        lines.append(f"| `{bucket}` | {int(count)} |")
    lines.append("")

    lines.append("## Gate Failures")
    if gate_failures:
        lines.append("| Gate | Status | Failed Step | Exit Code |")
        lines.append("| --- | --- | --- | --- |")
        for gf in gate_failures:
            lines.append(
                f"| `{gf.get('gate','')}` | `{gf.get('status','')}` | `{gf.get('failed_step','')}` | `{gf.get('exit_code','')}` |"
            )
    else:
        lines.append("- None")
    lines.append("")

    actionable_classes = {"authoritative_doc", "code_or_tooling"}
    generated_classes = {"derived_report", "generated_artifact"}
    secondary_classes = {"other_doc"}
    source_class_map: dict[str, str] = {}
    for r in rows:
        source = str(r.get("source_path", ""))
        klass = str(r.get("source_class", "")).strip()
        if source and klass and source not in source_class_map:
            source_class_map[source] = klass

    by_class: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for source_path, total in sources:
        klass = source_class_map.get(source_path) or _bucket_for_source(source_path)
        by_class[klass].append((source_path, total))

    lines.append("## Source Files With Misses (Full List)")
    lines.append("| SourceClass | Source | Total | Categories |")
    lines.append("| --- | --- | ---: | --- |")
    for source_path, total in sources:
        breakdown = source_breakdown.get(source_path, {})
        source_class = source_class_map.get(source_path) or _bucket_for_source(source_path)
        cat_text = ", ".join(f"{k}:{v}" for k, v in sorted(breakdown.items(), key=lambda kv: kv[0]))
        lines.append(f"| `{source_class}` | `{source_path}` | {int(total)} | `{cat_text}` |")
    lines.append("")

    lines.append("## Actionable Implementation Sources")
    lines.append("| SourceClass | Source | Rows |")
    lines.append("| --- | --- | ---: |")
    for klass in sorted(actionable_classes):
        for source_path, total in sorted(by_class.get(klass, []), key=lambda kv: (-int(kv[1]), kv[0])):
            lines.append(f"| `{klass}` | `{source_path}` | {int(total)} |")
    lines.append("")

    lines.append("## Non-Actionable Generated Sources")
    lines.append("| SourceClass | Source | Rows |")
    lines.append("| --- | --- | ---: |")
    for klass in sorted(generated_classes):
        for source_path, total in sorted(by_class.get(klass, []), key=lambda kv: (-int(kv[1]), kv[0])):
            lines.append(f"| `{klass}` | `{source_path}` | {int(total)} |")
    lines.append("")

    lines.append("## Secondary Documentation Sources")
    lines.append("| SourceClass | Source | Rows |")
    lines.append("| --- | --- | ---: |")
    for klass in sorted(secondary_classes):
        for source_path, total in sorted(by_class.get(klass, []), key=lambda kv: (-int(kv[1]), kv[0])):
            lines.append(f"| `{klass}` | `{source_path}` | {int(total)} |")
    lines.append("")

    lines.append("## Unique Requirement/Item IDs Seen In Miss Rows")
    lines.append(f"- Unique IDs (all files): `{len(ids)}`")
    lines.append(f"- Unique IDs (authoritative docs only): `{len(auth_ids)}`")
    lines.append("")
    lines.append("### IDs (Authoritative Docs)")
    lines.append("```text")
    for item_id in sorted(auth_ids):
        lines.append(f"{item_id} x{auth_ids[item_id]}")
    lines.append("```")
    lines.append("")

    lines.append("## Code Placeholder/TODO Misses")
    lines.append(f"- Total placeholder/TODO rows: `{len(code_placeholder_rows)}`")
    lines.append("| File | Rows |")
    lines.append("| --- | ---: |")
    for file_path, count in code_by_file.most_common():
        lines.append(f"| `{file_path}` | {int(count)} |")
    lines.append("")

    lines.append("## 4Pillars Upgrade Plan Coverage Check")
    lines.append("- Source doc: `docs/AutocapturePrime_4Pillars_Upgrade_Plan.md`")
    lines.append("- Method: count repo references to each `A*` / `A-*` item outside that source document.")
    lines.append("| Item | Line | Title | External Refs | Example Refs |")
    lines.append("| --- | ---: | --- | ---: | --- |")
    for item in four_pillars:
        refs = "; ".join(_quote_cell(x) for x in item.ref_examples) if item.ref_examples else "none"
        lines.append(
            f"| `{item.item_id}` | {item.line} | {_quote_cell(item.title)} | {item.external_refs} | {refs} |"
        )
    lines.append("")

    lines.append("## Regenerated Misses (Actionable Clusters)")
    lines.append("| Cluster ID | Scope | Evidence | Required Closure |")
    lines.append("| --- | --- | --- | --- |")
    cluster_rows: list[tuple[str, str, str, str]] = []

    if gate_failures:
        failed = ", ".join(
            f"{gf.get('gate','?')}:{gf.get('failed_step','')}" for gf in gate_failures
        )
        cluster_rows.append(
            (
                "MX-001",
                "Deterministic gates",
                failed,
                "Restore all failed gate steps to green with deterministic pass artifacts.",
            )
        )

    if code_placeholder_rows:
        files = ", ".join(f"`{p}`" for p, _ in code_by_file.most_common(5))
        cluster_rows.append(
            (
                "MX-002",
                "Code placeholder/TODO debt",
                files or "placeholder markers detected",
                "Replace placeholders with production logic or remove dead paths with tests.",
            )
        )

    blueprint_open = [
        r
        for r in rows
        if str(r.get("source_path", "")) == "docs/blueprints/autocapture_nx_blueprint.md"
        and str(r.get("category", "")) == "doc_open_checkbox"
    ]
    if blueprint_open:
        cluster_rows.append(
            (
                "MX-003",
                "Blueprint checklist backlog",
                f"{len(blueprint_open)} unchecked I-items in docs/blueprints/autocapture_nx_blueprint.md",
                "Close or explicitly defer each I-item with implementation/test evidence and updated status.",
            )
        )

    tracker_open = [
        r
        for r in rows
        if str(r.get("source_path", "")) == "docs/reports/feature_completeness_tracker.md"
        and str(r.get("category", "")) == "doc_open_checkbox"
    ]
    if tracker_open:
        cluster_rows.append(
            (
                "MX-004",
                "Feature completeness tracker backlog",
                f"{len(tracker_open)} unchecked entries in docs/reports/feature_completeness_tracker.md",
                "Reconcile tracker with executable evidence or annotate as informational-only generated output.",
            )
        )

    four_pillars_zero = [x for x in four_pillars if int(x.external_refs) == 0]
    if four_pillars_zero:
        sample = ", ".join(x.item_id for x in four_pillars_zero[:5])
        cluster_rows.append(
            (
                "MX-005",
                "4Pillars plan traceability gap",
                f"{len(four_pillars_zero)} items without external refs (e.g. {sample})",
                "Implement items or add concrete tracking artifacts/tests that reference each A-item.",
            )
        )

    derived_rows = [r for r in rows if str(r.get("source_class", "")) == "derived_report"]
    if derived_rows:
        cluster_rows.append(
            (
                "MX-006",
                "Report/document drift",
                f"{len(derived_rows)} rows from generated report docs",
                "Mark archival snapshots as informational and keep generated reports out of actionable closure criteria.",
            )
        )

    contract_rows = [
        r
        for r in rows
        if str(r.get("source_path", "")) in {
            "docs/autocapture_prime_UNDER_HYPERVISOR.md",
            "docs/codex_autocapture_prime_blueprint.md",
        }
    ]
    contract_open = [
        r
        for r in contract_rows
        if str(r.get("category", "")) in {"doc_contract_placeholder", "doc_open_item"}
    ]
    if contract_open:
        cluster_rows.append(
            (
                "MX-007",
                "Contract doc open placeholders/items",
                f"{len(contract_open)} unresolved placeholders/open items in today's contract docs",
                "Replace placeholders with concrete values and close listed open items with explicit implementation references.",
            )
        )

    required_artifacts = [
        r
        for r in contract_rows
        if str(r.get("category", "")) == "doc_required_artifact_missing"
    ]
    if required_artifacts:
        missing_paths = sorted(
            {
                str(r.get("reason", "")).replace("required artifact path missing: ", "").strip()
                for r in required_artifacts
            }
        )
        sample = ", ".join(f"`{p}`" for p in missing_paths[:4])
        cluster_rows.append(
            (
                "MX-008",
                "Contract-required artifacts missing",
                f"{len(required_artifacts)} missing artifacts (e.g. {sample})",
                "Create required artifacts and add deterministic tests that prove they are generated/validated by workflow.",
            )
        )

    if cluster_rows:
        for cid, scope, evidence, closure in cluster_rows:
            lines.append(f"| {cid} | {scope} | {evidence} | {closure} |")
    else:
        lines.append("| MX-000 | None | no actionable clusters detected | No remaining actionable misses from current inventory. |")
    lines.append("")

    lines.append("## Notes")
    lines.append(
        "- This file is generated from inventory data and is intentionally exhaustive; use the actionable clusters above to prioritize implementation sequencing."
    )
    lines.append("- Any regressions from this matrix should be treated as `DO_NOT_SHIP` until resolved or explicitly deferred.")
    lines.append("")

    return "\n".join(lines) + "\n"


def generate_matrix(repo_root: Path, input_json: Path, output_md: Path) -> None:
    inv = _load_json(input_json)
    rows = list(inv.get("rows", []))

    source_counts = Counter(str(r.get("source_path", "")) for r in rows)
    sorted_sources = sorted(source_counts.items(), key=lambda kv: (-int(kv[1]), kv[0]))

    source_breakdown: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        source = str(r.get("source_path", ""))
        cat = str(r.get("category", ""))
        source_breakdown[source][cat] += 1

    four_pillars = _parse_four_pillars_items(repo_root, "docs/AutocapturePrime_4Pillars_Upgrade_Plan.md")
    md = _render_markdown(
        inv=inv,
        rows=rows,
        sources=sorted_sources,
        source_breakdown={k: dict(v) for k, v in source_breakdown.items()},
        four_pillars=four_pillars,
    )

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(md, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate exhaustive remaining implementation matrix.")
    parser.add_argument(
        "--input-json",
        default="artifacts/repo_miss_inventory/latest.json",
        help="Path to miss inventory JSON",
    )
    parser.add_argument(
        "--output-md",
        default="docs/reports/implementation_matrix_remaining_2026-02-12.md",
        help="Path to output markdown matrix",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    generate_matrix(repo_root, repo_root / args.input_json, repo_root / args.output_md)
    print(
        json.dumps(
            {
                "ok": True,
                "input_json": str((repo_root / args.input_json).resolve()),
                "output_md": str((repo_root / args.output_md).resolve()),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
