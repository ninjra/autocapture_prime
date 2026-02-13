"""Validate the generated traceability manifest.

This is intentionally strict but low-resource:
- Ensures expected item IDs exist.
- Ensures every acceptance bullet has at least one validator path.
- Ensures validator paths exist on disk.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))


@dataclass(frozen=True)
class Issue:
    code: str
    detail: str


def _validator_class(path_text: str) -> str:
    p = path_text.strip()
    if not p:
        return "empty"
    if p.startswith("tests/"):
        return "test"
    if p.startswith("tools/"):
        name = Path(p).name
        if name.startswith("gate_"):
            return "gate"
        if p.endswith((".py", ".sh", ".ps1")):
            return "tool"
        return "tool_other"
    if p.startswith(("autocapture/", "autocapture_nx/", "plugins/")):
        return "code"
    if p.startswith("docs/"):
        return "doc"
    return "other"


def _expected_item_ids(repo_root: Path) -> set[str]:
    # Implementation matrix is the authoritative list of in-scope items.
    path = repo_root / "docs" / "reports" / "implementation_matrix.md"
    ids: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not (raw.startswith("| I") or raw.startswith("| FX")):
            continue
        cols = [c.strip() for c in raw.strip().strip("|").split("|")]
        if not cols or cols[0] in {"ItemID", "---"}:
            continue
        if cols[0].startswith(("I", "FX")):
            ids.add(cols[0])
    return ids


def validate_traceability(repo_root: Path, traceability_path: Path) -> tuple[bool, list[Issue]]:
    issues: list[Issue] = []
    data = json.loads(traceability_path.read_text(encoding="utf-8"))
    if int(data.get("version", 0) or 0) != 1:
        issues.append(Issue("bad_version", f"version={data.get('version')}"))
        return False, issues
    items = data.get("items")
    if not isinstance(items, list):
        issues.append(Issue("bad_items", "items_not_list"))
        return False, issues

    expected = _expected_item_ids(repo_root)
    got = {str(it.get("id", "")).strip() for it in items if isinstance(it, dict)}
    missing = sorted(expected - got)
    extra = sorted(got - expected)
    if missing:
        issues.append(Issue("missing_items", ",".join(missing[:20])))
    if extra:
        issues.append(Issue("extra_items", ",".join(extra[:20])))

    for it in items:
        if not isinstance(it, dict):
            continue
        item_id = str(it.get("id", "")).strip()
        bullets = it.get("acceptance_bullets", [])
        if not isinstance(bullets, list) or not bullets:
            issues.append(Issue("missing_acceptance", item_id))
            continue
        for b in bullets:
            if not isinstance(b, dict):
                issues.append(Issue("bad_bullet", item_id))
                continue
            text = str(b.get("text", "")).strip()
            validators = b.get("validators", [])
            if not text:
                issues.append(Issue("empty_bullet_text", item_id))
            if not isinstance(validators, list) or not validators:
                issues.append(Issue("missing_validators", f"{item_id}:{text[:60]}"))
                continue
            classes: list[str] = []
            for v in validators:
                vp = str(v).strip()
                if not vp:
                    issues.append(Issue("empty_validator", item_id))
                    continue
                classes.append(_validator_class(vp))
                p = repo_root / vp
                if not p.exists():
                    issues.append(Issue("validator_missing_path", f"{item_id}:{vp}"))
            # Require at least one executable validator per acceptance bullet.
            if not any(c in {"test", "gate", "tool"} for c in classes):
                issues.append(Issue("no_executable_validators", f"{item_id}:{text[:60]}"))
            # Documentation-only validators are not acceptable as closure evidence.
            if classes and all(c == "doc" for c in classes):
                issues.append(Issue("doc_only_validators", f"{item_id}:{text[:60]}"))

    return not issues, issues


def main() -> int:
    repo_root = _REPO_ROOT
    traceability_path = repo_root / "tools" / "traceability" / "traceability.json"
    ok, issues = validate_traceability(repo_root, traceability_path)
    if ok:
        print("OK: traceability manifest valid")
        return 0
    for issue in issues[:100]:
        print(f"{issue.code}: {issue.detail}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
