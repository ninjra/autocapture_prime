"""Generate a structured traceability manifest from curated repo reports.

This is a bootstrap generator. It intentionally relies on existing curated
evidence (implementation matrix and blueprint gap report) so we can start
gating determinism without a massive manual mapping pass.

Output: tools/traceability/traceability.json
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from tools.traceability.parse_markdown_tables import iter_pipe_table_rows  # noqa: E402


RE_GAP_NAME = re.compile(r"^blueprint-gap-(\d{4}-\d{2}-\d{2})\.md$")


@dataclass(frozen=True)
class MatrixRow:
    item_id: str
    phase: str
    title: str
    status: str
    evidence_cell: str
    tests_cell: str


def _split_cell(cell: str) -> list[str]:
    # Normalize common separators to '\n', then split.
    raw = (cell or "").replace("<br>", "\n")
    parts: list[str] = []
    for line in raw.splitlines():
        for sub in line.split(";"):
            val = sub.strip()
            if val:
                parts.append(val)
    # Preserve order while de-duping deterministically.
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _latest_gap_report(reports_dir: Path) -> Path:
    best = None
    best_date = ""
    for path in sorted(reports_dir.iterdir()):
        if not path.is_file():
            continue
        m = RE_GAP_NAME.match(path.name)
        if not m:
            continue
        date = m.group(1)
        if date > best_date:
            best_date = date
            best = path
    if best is None:
        raise SystemExit(f"No blueprint gap reports found in {reports_dir}")
    return best


def _load_blueprint_items() -> dict[str, dict]:
    items = json.loads((_REPO_ROOT / "tools" / "blueprint_items.json").read_text(encoding="utf-8"))
    by_id: dict[str, dict] = {}
    for it in items:
        it_id = str(it.get("id", "")).strip()
        if it_id:
            by_id[it_id] = it
    return by_id


def _load_matrix_rows() -> dict[str, MatrixRow]:
    path = _REPO_ROOT / "docs" / "reports" / "implementation_matrix.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    rows = iter_pipe_table_rows(lines, prefix="| ")
    by_id: dict[str, MatrixRow] = {}
    for row in rows:
        if not row.cols or row.cols[0] in {"ItemID", "---"}:
            continue
        item_id = row.cols[0]
        if not (item_id.startswith("I") or item_id.startswith("FX")):
            continue
        if len(row.cols) < 7:
            continue
        by_id[item_id] = MatrixRow(
            item_id=item_id,
            phase=row.cols[1],
            title=row.cols[2],
            status=row.cols[3],
            evidence_cell=row.cols[4],
            tests_cell=row.cols[6],
        )
    return by_id


def _load_gap_evidence() -> dict[str, list[str]]:
    path = _latest_gap_report(_REPO_ROOT / "docs" / "reports")
    lines = path.read_text(encoding="utf-8").splitlines()
    rows = iter_pipe_table_rows(lines, prefix="| I")
    by_id: dict[str, list[str]] = {}
    for row in rows:
        if not row.cols or row.cols[0] in {"ID", "---"}:
            continue
        if len(row.cols) < 5:
            continue
        item_id = row.cols[0]
        evidence = _split_cell(row.cols[4])
        by_id[item_id] = evidence
    return by_id


def _fx_acceptance() -> dict[str, list[str]]:
    # FX items don't exist in tools/blueprint_items.json; define explicit bullets here.
    return {
        "FX001": [
            "Fixture pipeline CLI ingests deterministic fixtures and produces queryable metadata without requiring network.",
            "Fixture query validation asserts answers include citations and verifiable evidence paths.",
            "Fixture pipeline emits deterministic plugin status reporting suitable for debugging.",
        ],
        "FX002": [
            "Model prep and reprocess workflow is deterministic and auditable (no remote binding, no deletion).",
            "All plugins load/execute in reprocess/query modes without sandbox permission errors under configured policies.",
            "Model manifest and identity overrides are validated deterministically.",
        ],
    }


def _validator_overrides() -> dict[str, list[str]]:
    # Bootstrap: fill known gaps where the curated reports don't list validators,
    # but deterministic tests/gates already exist (or were added).
    return {
        "I064": ["tests/test_dependency_pinning.py", "tools/gate_deps_lock.py", "tools/gate_doctor.py"],
        "I078": ["tests/test_ux_facade_parity.py", "tests/test_trace_facade.py"],
        "I079": ["tests/test_ux_facade_parity.py"],
        "I080": [
            "tests/test_ui_routes.py",
            "tests/test_ui_accessibility.py",
            "tests/test_settings_ui_contract.py",
            "tests/test_status_banner_ui.py",
        ],
        "I081": ["tests/test_watchdog_alerts.py", "tests/test_silence_alerts.py", "autocapture/web/routes/alerts.py"],
        "I082": ["tests/test_localhost_binding.py", "tests/test_web_auth_middleware.py"],
        "I083": ["tests/test_websocket_telemetry.py"],
        "I121": ["tests/test_egress_approval_store.py", "tests/test_egress_approval_workflow.py"],
    }


def _is_pathish(s: str) -> bool:
    return "/" in s or s.endswith(".py") or s.endswith(".json") or s.endswith(".md")


def _extract_validator_paths(paths: list[str]) -> list[str]:
    vals: list[str] = []
    for p in paths:
        if not _is_pathish(p):
            continue
        if p.startswith("tests/"):
            vals.append(p)
        elif p.startswith("tools/") and (
            p.startswith("tools/gate_")
            or p.startswith("tools/run_")
            or p.startswith("tools/state_layer_eval.py")
        ):
            vals.append(p)
    # Stable unique.
    seen: set[str] = set()
    out: list[str] = []
    for v in vals:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _normalize_paths(paths: list[str]) -> list[str]:
    # Keep repo-relative paths only; drop anything else.
    out: list[str] = []
    for p in paths:
        p = p.strip()
        if not p:
            continue
        if p.startswith(("/", "\\")):
            continue
        out.append(p)
    # Stable unique.
    seen: set[str] = set()
    uniq: list[str] = []
    for p in out:
        if p in seen:
            continue
        seen.add(p)
        uniq.append(p)
    return uniq


def _item_sort_key(item_id: str) -> tuple[int, int, str]:
    if item_id.startswith("FX"):
        m = re.fullmatch(r"FX(\d+)", item_id)
        n = int(m.group(1)) if m else 0
        return (0, n, item_id)
    m = re.fullmatch(r"I(\d+)", item_id)
    n = int(m.group(1)) if m else 0
    return (1, n, item_id)


def main() -> int:
    blueprint = _load_blueprint_items()
    matrix = _load_matrix_rows()
    gap_evidence = _load_gap_evidence()
    fx_acceptance = _fx_acceptance()
    overrides = _validator_overrides()

    item_ids = sorted(matrix.keys(), key=_item_sort_key)
    items_out: list[dict] = []
    for item_id in item_ids:
        row = matrix[item_id]
        acceptance: list[str] = []
        if item_id.startswith("I"):
            acceptance = list(blueprint.get(item_id, {}).get("acceptance_criteria") or [])
        else:
            acceptance = fx_acceptance.get(item_id, [])
        acceptance = [str(x).strip() for x in acceptance if str(x).strip()]

        evidence_paths: list[str] = []
        evidence_paths.extend(_split_cell(row.evidence_cell))
        evidence_paths.extend(_split_cell(row.tests_cell))
        evidence_paths.extend(gap_evidence.get(item_id, []))
        evidence_paths.extend(overrides.get(item_id, []))
        evidence_paths = _normalize_paths(evidence_paths)

        validators = _extract_validator_paths(evidence_paths)
        bullets = [{"text": b, "validators": list(validators)} for b in acceptance]

        items_out.append(
            {
                "id": item_id,
                "phase": row.phase,
                "title": row.title,
                "status": row.status,
                "evidence_paths": evidence_paths,
                "acceptance_bullets": bullets,
            }
        )

    out_path = _REPO_ROOT / "tools" / "traceability" / "traceability.json"
    payload = {"version": 1, "items": items_out}
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"OK: wrote {out_path.relative_to(_REPO_ROOT)} items={len(items_out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
