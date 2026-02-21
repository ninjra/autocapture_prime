#!/usr/bin/env python3
"""Generate a repo-wide inventory of likely incomplete implementation items.

This scanner is intentionally broad:
- walks all tracked + untracked repo files (excluding ignored),
- extracts explicit "open/partial/missing/blocked" requirement lines,
- captures unchecked checklist entries in docs,
- captures TODO/placeholder/not_configured markers in code,
- includes latest gate failure summary when present.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REQUIREMENT_ID_RE = re.compile(
    r"\b("
    r"SRC-\d{3}|MOD-\d{3}|I\d{3}|FX\d{3}|RM-\d{3}|"
    r"A\d{1,2}|A-[A-Z]+-\d{2}|"
    r"QRY-\d{3}|EVAL-\d{3}|ATTR-\d{3}|WSL-\d{3}|SEC-\d{3}|CAP-\d{3}|AUD-\d{3}|INP-\d{3}"
    r")\b"
)

STATUS_TOKEN_RE = re.compile(
    r"\b("
    r"open|partial|missing|blocked|incomplete|not implemented|"
    r"not_implemented|not configured|todo|no evidence"
    r")\b",
    flags=re.IGNORECASE,
)

CODE_TODO_RE = re.compile(
    r"^\s*#.*\b(TODO|FIXME|TBD|NOT IMPLEMENTED)\b",
    flags=re.IGNORECASE,
)

CHECKBOX_OPEN_RE = re.compile(r"^\s*[-*]\s+\[ \]\s+(.+)$")
CHECKBOX_DONE_RE = re.compile(r"^\s*[-*]\s+\[[xX]\]\s+(.+)$")

GENERATED_REPORT_PREFIXES = (
    "artifacts/repo_miss_inventory/",
    "docs/reports/full_repo_miss_inventory_",
)

# Historical/generated report snapshots are useful references but are not
# implementation debt sources. Exclude them from miss extraction to prevent
# stale "partial/missing" text from dominating current closure status.
ARCHIVAL_REPORT_PREFIXES = (
    "docs/reports/adversarial-redesign-gap-",
    "docs/deprecated/",
    "docs/implemented-ignore/",
)
ARCHIVAL_REPORT_EXACT = {
    "docs/reports/risk_register.md",
}

STATUS_VALUES = {
    "open",
    "partial",
    "missing",
    "blocked",
    "incomplete",
    "not implemented",
    "not_implemented",
    "not configured",
    "todo",
    "no evidence",
}

SPECIAL_AUTH_DOCS = {
    "AGENTS.md",
    "docs/AutocapturePrime_4Pillars_Upgrade_Plan.md",
    "docs/autocapture_prime_4pillars_optimization.md",
    "docs/windows-sidecar-capture-interface.md",
    "docs/autocapture_prime_UNDER_HYPERVISOR.md",
    "docs/codex_autocapture_prime_blueprint.md",
}

DOC_CONTRACT_DOCS = {
    "docs/autocapture_prime_UNDER_HYPERVISOR.md",
    "docs/codex_autocapture_prime_blueprint.md",
}

DOC_PLACEHOLDER_RE = re.compile(r"<[A-Z][A-Z0-9_-]*>")
BACKTICK_TOKEN_RE = re.compile(r"`([^`]+)`")
CAPABILITY_TOKEN_RE = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+){2,}$")
ARTIFACT_KEYWORD_RE = re.compile(r"\b(add|create|generate|produce|write|save|must|implement)\b", flags=re.IGNORECASE)
BACKLOG_STATUS_MATRIX_PATH = "docs/reports/autocapture_prime_4pillars_optimization_matrix.md"


@dataclass(frozen=True)
class MissRow:
    category: str
    item_id: str
    source_class: str
    source_path: str
    line: int
    reason: str
    snippet: str


def _run(repo_root: Path, args: list[str]) -> str:
    proc = subprocess.run(
        args,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return str(proc.stdout or "")


def _repo_files(repo_root: Path) -> list[Path]:
    tracked = _run(repo_root, ["git", "ls-files"]).splitlines()
    untracked = _run(repo_root, ["git", "ls-files", "--others", "--exclude-standard"]).splitlines()
    out: list[Path] = []
    seen: set[str] = set()
    for rel in tracked + untracked:
        rel = str(rel or "").strip()
        if not rel:
            continue
        if any(rel.startswith(prefix) for prefix in GENERATED_REPORT_PREFIXES):
            continue
        if any(rel.startswith(prefix) for prefix in ARCHIVAL_REPORT_PREFIXES):
            continue
        if rel in ARCHIVAL_REPORT_EXACT:
            continue
        if rel in seen:
            continue
        seen.add(rel)
        p = (repo_root / rel).resolve()
        if not p.exists() or not p.is_file():
            continue
        out.append(p)
    return out


def _classify_source(rel: str) -> str:
    if rel.startswith("docs/reports/"):
        return "derived_report"
    if rel.startswith("artifacts/"):
        return "generated_artifact"
    if rel in SPECIAL_AUTH_DOCS:
        return "authoritative_doc"
    if rel.startswith(("docs/blueprints/", "docs/spec/", "docs/specs/")):
        return "authoritative_doc"
    if rel.startswith("docs/"):
        return "other_doc"
    return "code_or_tooling"


def _looks_binary(blob: bytes) -> bool:
    if not blob:
        return False
    return b"\x00" in blob[:4096]


def _iter_text_lines(path: Path) -> Iterable[tuple[int, str]]:
    raw = path.read_bytes()
    if _looks_binary(raw):
        return []
    text = raw.decode("utf-8", errors="replace")
    return list(enumerate(text.splitlines(), start=1))


def _table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or stripped.count("|") < 2:
        return []
    return [c.strip().lower() for c in stripped.strip("|").split("|")]


def _cell_is_status(cell: str) -> bool:
    normalized = " ".join(str(cell or "").strip().lower().split())
    return normalized in STATUS_VALUES


def _line_has_requirement_status_marker(line: str) -> bool:
    cells = _table_cells(line)
    if cells:
        return any(_cell_is_status(c) for c in cells)
    return bool(
        re.search(
            r"\b(status|state)\b[^:]{0,16}:\s*(open|partial|missing|blocked|incomplete|not implemented|not configured|todo|no evidence)\b",
            line,
            flags=re.IGNORECASE,
        )
    )


def _collect_doc_status_misses(path: Path, rel: str, rows: list[MissRow]) -> None:
    source_class = _classify_source(rel)
    if source_class in {"derived_report", "generated_artifact"}:
        return
    in_master_backlog = False
    backlog_status_map = _load_backlog_status_map(path.parents[1])
    cli_text = ""
    cli_path = path.parents[1] / "autocapture_nx" / "cli.py"
    if cli_path.exists():
        try:
            cli_text = cli_path.read_text(encoding="utf-8")
        except Exception:
            cli_text = ""
    for lineno, line in _iter_text_lines(path):
        stripped = line.strip()
        if not stripped:
            continue

        low = stripped.lower()
        if "master backlog" in low:
            in_master_backlog = True
        elif in_master_backlog and stripped.startswith("#"):
            in_master_backlog = False

        m_open = CHECKBOX_OPEN_RE.match(stripped)
        if m_open:
            snippet = m_open.group(1).strip()
            id_match = REQUIREMENT_ID_RE.search(snippet)
            rows.append(
                MissRow(
                    category="doc_open_checkbox",
                    item_id=id_match.group(0) if id_match else "",
                    source_class=source_class,
                    source_path=rel,
                    line=lineno,
                    reason="unchecked checklist item",
                    snippet=snippet,
                )
            )
            continue

        # Requirement-like row with explicit open/partial/missing markers.
        ids = [m.group(0) for m in REQUIREMENT_ID_RE.finditer(line)]
        has_status = _line_has_requirement_status_marker(line)
        if ids and has_status:
            for item_id in ids:
                rows.append(
                    MissRow(
                        category="doc_requirement_status",
                        item_id=item_id,
                        source_class=source_class,
                        source_path=rel,
                        line=lineno,
                        reason="requirement linked to open/partial/missing marker",
                        snippet=stripped[:240],
                    )
                )

        # Table rows with explicit "missing" or "partial" even without item ids.
        if _table_cells(line) and has_status and not ids:
            rows.append(
                MissRow(
                    category="doc_table_status",
                    item_id="",
                    source_class=source_class,
                    source_path=rel,
                    line=lineno,
                    reason="table row contains open/partial/missing marker",
                    snippet=stripped[:240],
                )
            )

        # Authoritative backlog rows with explicit priority markers are treated
        # as outstanding until mapped in implementation artifacts.
        if source_class == "authoritative_doc" and in_master_backlog and ids:
            has_priority = bool(re.search(r"\bP[0-3]\b", stripped))
            backlog_ids = [
                item
                for item in ids
                if re.match(r"^(QRY|EVAL|ATTR|WSL|SEC|CAP|AUD|INP)-\d{3}$", item)
            ]
            if has_priority and backlog_ids:
                for item_id in backlog_ids:
                    mapped_status = str(backlog_status_map.get(item_id, "")).strip().lower()
                    if mapped_status == "complete":
                        continue
                    rows.append(
                        MissRow(
                            category="doc_backlog_row",
                            item_id=item_id,
                            source_class=source_class,
                            source_path=rel,
                            line=lineno,
                            reason=(
                                "authoritative backlog item requires implementation mapping"
                                if not mapped_status
                                else f"authoritative backlog item status={mapped_status}"
                            ),
                            snippet=stripped[:240],
                        )
                    )

        # Authoritative docs can declare concrete CLI contracts; fail if missing.
        if source_class == "authoritative_doc" and "autocapture setup --profile" in low:
            if 'add_parser("setup")' not in cli_text:
                rows.append(
                    MissRow(
                        category="doc_cli_contract_missing",
                        item_id="",
                        source_class=source_class,
                        source_path=rel,
                        line=lineno,
                        reason="required CLI command missing: setup",
                        snippet=stripped[:240],
                    )
                )
        if source_class == "authoritative_doc" and "autocapture gate --profile" in low:
            if 'add_parser("gate")' not in cli_text:
                rows.append(
                    MissRow(
                        category="doc_cli_contract_missing",
                        item_id="",
                        source_class=source_class,
                        source_path=rel,
                        line=lineno,
                        reason="required CLI command missing: gate",
                        snippet=stripped[:240],
                    )
                )


def _load_backlog_status_map(repo_root: Path) -> dict[str, str]:
    path = repo_root / BACKLOG_STATUS_MATRIX_PATH
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        if line.strip().startswith("| ID ") or line.strip().startswith("| ---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        item_id = str(cells[0]).strip()
        status = str(cells[1]).strip()
        if not re.match(r"^(QRY|EVAL|ATTR|WSL|SEC|CAP|AUD|INP)-\d{3}$", item_id):
            continue
        out[item_id] = status
    return out


def _looks_repo_relative_path(token: str) -> bool:
    val = str(token or "").strip().strip(".,;:")
    if not val:
        return False
    if "://" in val:
        return False
    if val.startswith(("$", "<", ">", "http")):
        return False
    if " " in val:
        return False
    if "/" not in val:
        return False
    return bool(
        val.startswith(
            (
                "docs/",
                "tests/",
                "plugins/",
                "contracts/",
                "tools/",
                "autocapture/",
                "autocapture_nx/",
                "config/",
            )
        )
    )


def _collect_doc_contract_misses(repo_root: Path, path: Path, rel: str, rows: list[MissRow]) -> None:
    if rel not in DOC_CONTRACT_DOCS:
        return
    source_class = _classify_source(rel)
    in_open_items = False
    in_artifact_block = False
    artifact_base_dirs: list[str] = []
    capability_cache: dict[str, bool] = {}

    for lineno, line in _iter_text_lines(path):
        stripped = line.strip()
        if not stripped:
            continue

        for m in DOC_PLACEHOLDER_RE.finditer(stripped):
            rows.append(
                MissRow(
                    category="doc_contract_placeholder",
                    item_id="",
                    source_class=source_class,
                    source_path=rel,
                    line=lineno,
                    reason=f"unresolved placeholder token: {m.group(0)}",
                    snippet=stripped[:240],
                )
            )

        lower = stripped.lower()
        if lower.startswith("## open items to fill in") or lower.startswith("### open items to fill in"):
            in_open_items = True
            continue
        if in_open_items and stripped.startswith("#"):
            in_open_items = False
        if in_open_items and stripped.startswith("- "):
            rows.append(
                MissRow(
                    category="doc_open_item",
                    item_id="",
                    source_class=source_class,
                    source_path=rel,
                    line=lineno,
                    reason="open item listed in contract doc",
                    snippet=stripped[2:].strip()[:240],
                )
            )
            continue

        keyword_hit = bool(ARTIFACT_KEYWORD_RE.search(stripped))
        if keyword_hit and stripped.endswith(":"):
            in_artifact_block = True
            artifact_base_dirs = []
        elif in_artifact_block and (not stripped.startswith("- ")):
            in_artifact_block = False
            artifact_base_dirs = []

        tokens = [str(m.group(1) or "").strip() for m in BACKTICK_TOKEN_RE.finditer(stripped)]
        if not tokens:
            continue
        if not keyword_hit and not in_artifact_block:
            continue
        for token in tokens:
            value = token.strip().strip(".,;:")
            if _looks_repo_relative_path(value):
                if value.endswith("/"):
                    artifact_base_dirs.append(value)
                if not (repo_root / value).exists():
                    rows.append(
                        MissRow(
                            category="doc_required_artifact_missing",
                            item_id="",
                            source_class=source_class,
                            source_path=rel,
                            line=lineno,
                            reason=f"required artifact path missing: {value}",
                            snippet=stripped[:240],
                        )
                    )
                continue

            if "/" not in value and artifact_base_dirs:
                for base in artifact_base_dirs:
                    candidate = f"{base}{value}"
                    if not (repo_root / candidate).exists():
                        rows.append(
                            MissRow(
                                category="doc_required_artifact_missing",
                                item_id="",
                                source_class=source_class,
                                source_path=rel,
                                line=lineno,
                                reason=f"required artifact path missing: {candidate}",
                                snippet=stripped[:240],
                            )
                        )

            if CAPABILITY_TOKEN_RE.match(value) and ("capabilit" in lower or "implement" in lower):
                if value not in capability_cache:
                    raw = _run(repo_root, ["rg", "-n", "-F", value, "--hidden", "--glob", "!.git/*"])
                    hits = [ln for ln in raw.splitlines() if ln and not ln.startswith(f"{rel}:")]
                    capability_cache[value] = bool(hits)
                if not capability_cache[value]:
                    rows.append(
                        MissRow(
                            category="doc_required_capability_missing",
                            item_id="",
                            source_class=source_class,
                            source_path=rel,
                            line=lineno,
                            reason=f"required capability token not found in repo: {value}",
                            snippet=stripped[:240],
                        )
                    )


def _collect_code_todo_misses(path: Path, rel: str, rows: list[MissRow]) -> None:
    source_class = _classify_source(rel)
    for lineno, line in _iter_text_lines(path):
        m = CODE_TODO_RE.search(line)
        if not m:
            continue
        rows.append(
            MissRow(
                category="code_todo_placeholder",
                item_id="",
                source_class=source_class,
                source_path=rel,
                line=lineno,
                reason=f"code marker: {m.group(1)}",
                snippet=line.strip()[:240],
            )
        )


def _gate_failures(repo_root: Path) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    report = repo_root / "tools" / "run_all_tests_report.json"
    if report.exists():
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
            status = str(data.get("status") or "").strip()
            if status and status != "ok":
                out.append(
                    {
                        "gate": "tools/run_all_tests_report.json",
                        "status": status,
                        "failed_step": str(data.get("failed_step") or ""),
                        "exit_code": str(data.get("exit_code") or ""),
                    }
                )
        except Exception:
            pass
    return out


def _dedupe(rows: list[MissRow]) -> list[MissRow]:
    seen: set[tuple[str, str, str, str, int, str]] = set()
    out: list[MissRow] = []
    for row in rows:
        key = (row.category, row.item_id, row.source_class, row.source_path, row.line, row.reason)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    out.sort(key=lambda r: (r.category, r.item_id, r.source_path, r.line))
    return out


def _write_report(
    *,
    repo_root: Path,
    rows: list[MissRow],
    gate_failures: list[dict[str, str]],
    out_json: Path,
    out_md: Path,
    scanned_files: int,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    summary = {
        "generated_utc": now,
        "scanned_files": scanned_files,
        "rows_total": len(rows),
        "gate_failures_total": len(gate_failures),
        "categories": {},
        "source_classes": {},
    }
    for row in rows:
        summary["categories"][row.category] = int(summary["categories"].get(row.category, 0)) + 1
        summary["source_classes"][row.source_class] = int(summary["source_classes"].get(row.source_class, 0)) + 1

    payload = {
        "summary": summary,
        "gate_failures": gate_failures,
        "rows": [asdict(row) for row in rows],
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    md_lines: list[str] = []
    md_lines.append("# Full Repo Miss Inventory")
    md_lines.append("")
    md_lines.append(f"- Generated: `{now}`")
    md_lines.append(f"- Scanned files: `{scanned_files}`")
    md_lines.append(f"- Miss rows: `{len(rows)}`")
    md_lines.append(f"- Gate failures: `{len(gate_failures)}`")
    md_lines.append("")
    md_lines.append("## Source Classes")
    md_lines.append("| Source Class | Count |")
    md_lines.append("| --- | ---: |")
    for klass, count in sorted(summary["source_classes"].items(), key=lambda kv: (-int(kv[1]), kv[0])):
        md_lines.append(f"| `{klass}` | {int(count)} |")
    md_lines.append("")

    md_lines.append("## Gate Failures")
    if gate_failures:
        md_lines.append("| Gate | Status | Failed Step | Exit Code |")
        md_lines.append("| --- | --- | --- | --- |")
        for gf in gate_failures:
            md_lines.append(
                f"| `{gf.get('gate','')}` | `{gf.get('status','')}` | `{gf.get('failed_step','')}` | `{gf.get('exit_code','')}` |"
            )
    else:
        md_lines.append("- None")
    md_lines.append("")

    md_lines.append("## Miss Rows")
    md_lines.append("| Category | Item | SourceClass | Source | Line | Reason | Snippet |")
    md_lines.append("| --- | --- | --- | --- | ---: | --- | --- |")
    for row in rows:
        item = row.item_id or "-"
        snippet = row.snippet.replace("|", "\\|")
        md_lines.append(
            f"| `{row.category}` | `{item}` | `{row.source_class}` | `{row.source_path}` | {row.line} | {row.reason} | {snippet} |"
        )
    md_lines.append("")

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-json", default="artifacts/repo_miss_inventory/latest.json")
    parser.add_argument("--out-md", default="docs/reports/full_repo_miss_inventory_2026-02-12.md")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    files = _repo_files(repo_root)
    rows: list[MissRow] = []

    doc_ext = {".md", ".txt", ".rst"}
    code_ext = {".py", ".sh", ".ps1", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml"}

    for path in files:
        rel = str(path.relative_to(repo_root))
        suffix = path.suffix.lower()
        if suffix in doc_ext:
            _collect_doc_status_misses(path, rel, rows)
            _collect_doc_contract_misses(repo_root, path, rel, rows)
        if suffix in code_ext:
            _collect_code_todo_misses(path, rel, rows)

    rows = _dedupe(rows)
    gate_failures = _gate_failures(repo_root)
    out_json = (repo_root / args.out_json).resolve()
    out_md = (repo_root / args.out_md).resolve()
    _write_report(
        repo_root=repo_root,
        rows=rows,
        gate_failures=gate_failures,
        out_json=out_json,
        out_md=out_md,
        scanned_files=len(files),
    )

    print(
        json.dumps(
            {
                "ok": True,
                "scanned_files": len(files),
                "rows_total": len(rows),
                "gate_failures_total": len(gate_failures),
                "out_json": str(out_json),
                "out_md": str(out_md),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
