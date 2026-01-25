"""Prompt proposal generation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from autocapture.core.hashing import hash_canonical
from autocapture.promptops.patch import create_patch


def propose_prompt(
    current_prompt: str,
    snapshot: dict[str, Any],
    *,
    strategy: str = "append_sources",
    created_at: str | None = None,
) -> dict[str, Any]:
    sources = snapshot.get("sources", [])
    if strategy == "append_sources":
        lines = ["", "# Sources"]
        for item in sources:
            short = str(item.get("sha256", ""))[:12]
            label = item.get("source_id") or item.get("path") or "source"
            lines.append(f"- {label}: {short}")
        proposal = current_prompt.rstrip() + "\n" + "\n".join(lines) + "\n"
    else:
        proposal = current_prompt

    created_at = created_at or datetime.now(timezone.utc).isoformat()
    diff = create_patch(current_prompt, proposal)
    proposal_id = hash_canonical(
        {
            "proposal": proposal,
            "sources": sources,
            "strategy": strategy,
        }
    )
    return {
        "proposal_id": proposal_id,
        "created_at": created_at,
        "proposal": proposal,
        "diff": diff,
        "sources": sources,
        "combined_hash": snapshot.get("combined_hash"),
    }
