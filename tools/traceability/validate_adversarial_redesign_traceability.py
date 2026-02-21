"""Validate adversarial redesign traceability manifest."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from tools.traceability.adversarial_redesign_inventory import iter_redesign_items  # noqa: E402


@dataclass(frozen=True)
class Issue:
    code: str
    detail: str


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(*, require_implemented: bool) -> tuple[bool, list[Issue]]:
    doc_path = _REPO_ROOT / "docs" / "autocapture_prime_adversarial_redesign.md"
    trace_path = _REPO_ROOT / "tools" / "traceability" / "adversarial_redesign_traceability.json"
    schema_path = _REPO_ROOT / "tools" / "traceability" / "adversarial_redesign.schema.json"

    expected = {it.item_id for it in iter_redesign_items(doc_path)}
    payload = _load_json(trace_path)
    schema = _load_json(schema_path)
    issues: list[Issue] = []

    try:
        import jsonschema  # type: ignore

        try:
            jsonschema.validate(payload, schema)
        except Exception as exc:
            issues.append(Issue("schema", str(exc)))
            return False, issues
    except Exception:
        # Best-effort: schema validation is optional in minimal envs.
        pass

    items = payload.get("items", []) if isinstance(payload, dict) else []
    seen: set[str] = set()
    if not isinstance(items, list):
        issues.append(Issue("shape", "items_not_list"))
        return False, issues
    for item in items:
        if not isinstance(item, dict):
            issues.append(Issue("shape", "item_not_object"))
            continue
        rid = str(item.get("id", "")).strip()
        if not rid:
            issues.append(Issue("id", "missing_id"))
            continue
        if rid in seen:
            issues.append(Issue("dup", f"duplicate:{rid}"))
            continue
        seen.add(rid)
        status = str(item.get("status", "")).strip()
        if status not in {"missing", "partial", "implemented"}:
            issues.append(Issue("status", f"invalid_status:{rid}:{status}"))
        validators = item.get("validators", [])
        if status == "implemented":
            if not isinstance(validators, list) or not [v for v in validators if str(v).strip()]:
                issues.append(Issue("validators", f"implemented_missing_validators:{rid}"))
        if require_implemented and status != "implemented":
            issues.append(Issue("missing", f"not_implemented:{rid}:{status}"))

    missing = sorted(expected - seen)
    extra = sorted(seen - expected)
    for rid in missing:
        issues.append(Issue("missing_id", rid))
    for rid in extra:
        issues.append(Issue("extra_id", rid))
    return not issues, issues


def main() -> int:
    # Default to structural validation only. The hard coverage gate sets this to "1".
    require = os.getenv("AUTOCAPTURE_REQUIRE_ADVERSARIAL_REDESIGN_IMPLEMENTED", "0").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    ok, issues = validate(require_implemented=require)
    if ok:
        print("OK: adversarial redesign coverage")
        return 0
    for issue in issues[:120]:
        print(f"{issue.code}: {issue.detail}")
    print(f"FAIL: adversarial redesign coverage (issues={len(issues)})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
