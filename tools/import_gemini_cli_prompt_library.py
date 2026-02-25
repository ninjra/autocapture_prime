#!/usr/bin/env python3
"""Import Gemini CLI prompt-library ideas into PromptOps source files.

This importer reads command TOML files from:
https://github.com/harish-garg/gemini-cli-prompt-library

It produces:
1) A deterministic JSON catalog with extracted prompt metadata.
2) A compact Markdown source file that PromptOps can snapshot cheaply at runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Any


SOURCE_REPO_URL = "https://github.com/harish-garg/gemini-cli-prompt-library"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _first_heading(prompt_text: str, fallback: str) -> str:
    for raw in prompt_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            return line.lstrip("#").strip() or fallback
        break
    return fallback


def _starter_excerpt(prompt_text: str, *, max_chars: int = 280) -> str:
    cleaned = " ".join(str(prompt_text or "").strip().split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def _extract_principles(readme_text: str) -> list[str]:
    if not readme_text:
        return []
    marker = "## 📚 Prompt Engineering Tips"
    idx = readme_text.find(marker)
    if idx < 0:
        return []
    tail = readme_text[idx:]
    next_idx = tail.find("\n## ", 1)
    section = tail if next_idx < 0 else tail[:next_idx]
    matches = re.findall(r"###\s+\d+\.\s+\*\*(.+?)\*\*", section)
    out: list[str] = []
    for item in matches:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _load_prompt_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return None
    if len(path.parts) < 3:
        return None
    category = path.parent.name
    slug = path.stem
    command_id = f"{category}.{slug}"
    title = _first_heading(prompt, fallback=slug.replace("-", " ").title())
    lines = [line for line in prompt.splitlines() if line.strip()]
    return {
        "id": command_id,
        "category": category,
        "slug": slug,
        "command": f"/{category}:{slug}",
        "title": title,
        "line_count": int(len(lines)),
        "prompt_sha256": _sha256_text(prompt),
        "starter_excerpt": _starter_excerpt(prompt),
        "prompt_text": prompt,
    }


def build_payload(repo_root: Path) -> dict[str, Any]:
    commands_root = repo_root / "commands"
    files = sorted(commands_root.glob("*/*.toml"))
    prompts: list[dict[str, Any]] = []
    for file_path in files:
        row = _load_prompt_file(file_path)
        if row is not None:
            prompts.append(row)
    readme = (repo_root / "README.md").read_text(encoding="utf-8") if (repo_root / "README.md").exists() else ""
    principles = _extract_principles(readme)
    payload = {
        "schema_version": 1,
        "source_repo": SOURCE_REPO_URL,
        "source_path": str(repo_root),
        "prompt_count": int(len(prompts)),
        "principles": principles,
        "commands": prompts,
    }
    payload["content_hash"] = _sha256_text(
        json.dumps(
            {
                "source_repo": payload["source_repo"],
                "prompt_count": payload["prompt_count"],
                "principles": principles,
                "commands": [{k: v for k, v in row.items() if k != "prompt_text"} for row in prompts],
            },
            sort_keys=True,
        )
    )
    return payload


def render_runtime_source(payload: dict[str, Any]) -> str:
    principles = payload.get("principles", [])
    commands = payload.get("commands", [])
    lines: list[str] = [
        "# PromptOps Idea Pack: Gemini CLI Prompt Library",
        "",
        "Imported ideas and reusable prompt patterns for PromptOps query/model optimization.",
        "",
        f"- Source: {payload.get('source_repo', SOURCE_REPO_URL)}",
        f"- Prompt count: {int(payload.get('prompt_count', 0) or 0)}",
        f"- Content hash: {payload.get('content_hash', '')}",
        "",
        "## Prompt Engineering Principles",
    ]
    if isinstance(principles, list) and principles:
        for item in principles:
            lines.append(f"- {str(item)}")
    else:
        lines.append("- Be specific, structured, and explicit about output format.")
    lines.extend(["", "## Command Pattern Catalog"])
    if isinstance(commands, list):
        for row in commands:
            if not isinstance(row, dict):
                continue
            command = str(row.get("command") or "")
            title = str(row.get("title") or "")
            excerpt = str(row.get("starter_excerpt") or "")
            sig = str(row.get("prompt_sha256") or "")[:12]
            lines.append(f"- {command} | {title} | sig={sig}")
            if excerpt:
                lines.append(f"  - intent: {excerpt}")
    return "\n".join(lines).rstrip() + "\n"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Gemini CLI prompt library into PromptOps sources.")
    parser.add_argument("--repo", required=True, help="Path to cloned gemini-cli-prompt-library repo.")
    parser.add_argument(
        "--catalog-out",
        default="promptops/sources/gemini_cli_prompt_catalog.json",
        help="Output JSON catalog path.",
    )
    parser.add_argument(
        "--runtime-out",
        default="promptops/sources/gemini_cli_prompt_ideas.md",
        help="Output compact runtime source path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = Path(str(args.repo)).expanduser().resolve()
    if not repo.exists():
        raise SystemExit(f"repo path not found: {repo}")
    payload = build_payload(repo)
    catalog_out = Path(str(args.catalog_out)).expanduser()
    runtime_out = Path(str(args.runtime_out)).expanduser()
    _write_json(catalog_out, payload)
    _write_text(runtime_out, render_runtime_source(payload))
    print(
        json.dumps(
            {
                "ok": True,
                "source_repo": SOURCE_REPO_URL,
                "repo": str(repo),
                "prompt_count": int(payload.get("prompt_count", 0) or 0),
                "catalog_out": str(catalog_out),
                "runtime_out": str(runtime_out),
                "content_hash": str(payload.get("content_hash") or ""),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
