"""Coverage gate ensuring spec completeness."""

from __future__ import annotations

from pathlib import Path

import yaml


SPEC_PATH = Path("docs/spec/autocapture_mx_spec.yaml")


def run() -> dict:
    issues: list[str] = []
    if not SPEC_PATH.exists():
        return {"ok": False, "issues": ["spec_missing"]}
    data = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    reqs = data.get("requirements", [])
    seen: set[str] = set()
    for req in reqs:
        req_id = req.get("id")
        if not req_id:
            issues.append("missing_id")
            continue
        if req_id in seen:
            issues.append(f"duplicate_id:{req_id}")
        seen.add(req_id)
        if not req.get("artifacts"):
            issues.append(f"no_artifacts:{req_id}")
        if not req.get("validators"):
            issues.append(f"no_validators:{req_id}")
    return {"ok": len(issues) == 0, "issues": issues}
