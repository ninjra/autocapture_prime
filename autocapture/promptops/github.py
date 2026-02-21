"""Optional GitHub integration for prompt ops."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def create_pull_request(
    title: str,
    body: str,
    diff: str,
    *,
    enabled: bool = False,
    output_path: str = "artifacts/promptops_pr.json",
) -> dict[str, Any]:
    if not enabled:
        return {"ok": False, "reason": "github_disabled"}
    payload = {"title": title, "body": body, "diff": diff}
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return {"ok": True, "path": str(path)}
