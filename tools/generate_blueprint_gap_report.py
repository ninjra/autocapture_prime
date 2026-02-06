"""Generate deterministic blueprint gap report from traceability manifest.

This produces a stable 'latest' report file (no timestamps embedded) so we can
freshness-gate it. Historical dated reports can still be kept, but the gate
should target the stable file.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GapRow:
    item_id: str  # I001
    phase: str
    title: str
    status: str  # implemented/missing
    evidence: list[str]


def _load_traceability(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "tools" / "traceability" / "traceability.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _load_blueprint_items(repo_root: Path) -> dict[str, dict[str, Any]]:
    items = json.loads((repo_root / "tools" / "blueprint_items.json").read_text(encoding="utf-8"))
    by_id: dict[str, dict[str, Any]] = {}
    for it in items:
        it_id = str(it.get("id", "")).strip()
        if it_id:
            by_id[it_id] = it
    return by_id


def _evidence_filter(paths: list[str]) -> list[str]:
    # Keep deterministic, repo-relative, citeable paths.
    allow_prefixes = (
        "autocapture_nx/",
        "autocapture/",
        "plugins/",
        "contracts/",
        "config/",
        "tools/",
        "tests/",
        "pyproject.toml",
        "requirements.lock.json",
    )
    out: list[str] = []
    for p in paths:
        p = str(p).strip()
        if not p:
            continue
        if p.startswith(allow_prefixes):
            out.append(p)
    # Stable unique order.
    seen: set[str] = set()
    uniq: list[str] = []
    for p in out:
        if p in seen:
            continue
        seen.add(p)
        uniq.append(p)
    return uniq


def _implemented(item: dict[str, Any], repo_root: Path) -> bool:
    bullets = item.get("acceptance_bullets", [])
    if not isinstance(bullets, list) or not bullets:
        return False
    for b in bullets:
        if not isinstance(b, dict):
            return False
        validators = b.get("validators", [])
        if not isinstance(validators, list) or not validators:
            return False
        for v in validators:
            p = repo_root / str(v)
            if not p.exists():
                return False
    return True


def _build_rows(repo_root: Path) -> list[GapRow]:
    trace = _load_traceability(repo_root)
    items = trace.get("items", [])
    if not isinstance(items, list):
        raise SystemExit("traceability.json missing items list")
    items_by_id = {str(it.get("id", "")).strip(): it for it in items if isinstance(it, dict)}
    blueprint = _load_blueprint_items(repo_root)

    rows: list[GapRow] = []
    for item_id, spec in sorted(blueprint.items()):
        item = items_by_id.get(item_id) or {}
        status = "implemented" if _implemented(item, repo_root) else "missing"
        evidence_paths = _evidence_filter(list(item.get("evidence_paths", []) or []))
        # Fall back to enforcement_location / regression_detection locations as citeable hints.
        if not evidence_paths:
            ev = []
            ev.extend(spec.get("enforcement_location") or [])
            ev.extend(spec.get("regression_detection") or [])
            evidence_paths = _evidence_filter([str(x) for x in ev if str(x).strip()])
        phase = str(spec.get("phase", "")).strip() or str(item.get("phase", "")).strip()
        title = str(spec.get("title", "")).strip() or str(item.get("title", "")).strip()
        rows.append(GapRow(item_id=item_id, phase=phase, title=title, status=status, evidence=evidence_paths))

    return rows


def _render_report(rows: list[GapRow]) -> str:
    lines: list[str] = []
    lines.append("# Blueprint Gap Tracker (Autocapture NX)")
    lines.append("")
    lines.append("Generated: deterministic")
    lines.append("")
    lines.append("Status legend:")
    lines.append("- implemented: every acceptance bullet has at least one deterministic validator path and all paths exist")
    lines.append("- missing: one or more acceptance bullets lack validators, or validator paths are missing")
    lines.append("")
    lines.append("| ID | Phase | Title | Status | Evidence |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in sorted(rows, key=lambda x: x.item_id):
        evidence_cell = "<br>".join(r.evidence)
        lines.append(f"| {r.item_id} | {r.phase} | {r.title} | {r.status} | {evidence_cell} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="docs/reports/blueprint-gap-latest.md")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    out_path = (repo_root / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out).resolve()

    rows = _build_rows(repo_root)
    content = _render_report(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    print(f"OK: wrote {out_path.relative_to(repo_root) if out_path.is_relative_to(repo_root) else out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

