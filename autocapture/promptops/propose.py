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
    elif strategy in {"normalize_query", "rewrite_query"}:
        proposal = _normalize_query_prompt(current_prompt)
    elif strategy == "model_contract":
        proposal = _enforce_model_contract(current_prompt)
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


def _normalize_query_prompt(prompt: str) -> str:
    text = " ".join(str(prompt or "").strip().split())
    if not text:
        return text
    # Normalize obvious shorthand without changing intent.
    replacements = {
        " u ": " you ",
        " pls ": " please ",
        " w/ ": " with ",
    }
    padded = f" {text} "
    for old, new in replacements.items():
        padded = padded.replace(old, new)
    text = " ".join(padded.strip().split())
    if text and text[-1] not in {"?", ".", "!"}:
        text = f"{text}?"
    return text


def _enforce_model_contract(prompt: str) -> str:
    text = str(prompt or "").strip()
    if not text:
        return text
    suffix = (
        "\n\n"
        "Answer policy:\n"
        "- Prefer correctness over speed.\n"
        "- Use only grounded evidence from provided context.\n"
        "- If evidence is insufficient, explicitly return indeterminate.\n"
    )
    if "Answer policy:" in text:
        return text
    return text + suffix
