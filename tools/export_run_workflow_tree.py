#!/usr/bin/env python3
"""Export a concise workflow-tree diagram from a query result/report JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _resolve_query_payload(payload: dict[str, Any]) -> dict[str, Any]:
    # Preferred order: fully arbitrated query output, then explicit query payload,
    # then basic fallback.
    for key in ("query", "query_arbitrated", "query_result", "query_basic"):
        value = payload.get(key)
        if isinstance(value, dict) and isinstance(value.get("answer"), dict):
            return value
    if isinstance(payload.get("answer"), dict):
        return payload
    return {}


def _edge_lines(tree: dict[str, Any]) -> list[tuple[str, str]]:
    edges = tree.get("edges", []) if isinstance(tree.get("edges", []), list) else []
    out: list[tuple[str, str]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("from") or "").strip()
        dst = str(edge.get("to") or "").strip()
        if src and dst:
            out.append((src, dst))
    return out


def _render_markdown(result: dict[str, Any], *, source_path: str) -> str:
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    display = answer.get("display", {}) if isinstance(answer.get("display", {}), dict) else {}
    summary = str(display.get("summary") or "").strip()
    bullets = display.get("bullets", []) if isinstance(display.get("bullets", []), list) else []
    processing = result.get("processing", {}) if isinstance(result.get("processing", {}), dict) else {}
    attribution = processing.get("attribution", {}) if isinstance(processing.get("attribution", {}), dict) else {}
    providers = attribution.get("providers", []) if isinstance(attribution.get("providers", []), list) else []
    tree = attribution.get("workflow_tree", {}) if isinstance(attribution.get("workflow_tree", {}), dict) else {}
    edges = _edge_lines(tree)

    lines: list[str] = []
    lines.append("# Query Workflow Tree")
    lines.append("")
    lines.append(f"- Source: `{source_path}`")
    if summary:
        lines.append(f"- Answer summary: `{summary}`")
    if bullets:
        for bullet in bullets[:8]:
            lines.append(f"- Answer detail: `{str(bullet).strip()}`")

    lines.append("")
    lines.append("## Plugin Contributions")
    if not providers:
        lines.append("- (none)")
    else:
        for item in providers:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("provider_id") or "").strip() or "unknown"
            claims = int(item.get("claim_count", 0) or 0)
            cites = int(item.get("citation_count", 0) or 0)
            doc_kinds = ", ".join(str(x) for x in (item.get("doc_kinds") or [])[:6]) or "-"
            lines.append(f"- `{pid}`: claims={claims}, citations={cites}, doc_kinds={doc_kinds}")

    lines.append("")
    lines.append("## Mermaid")
    lines.append("```mermaid")
    lines.append("graph TD")
    if edges:
        for src, dst in edges:
            lines.append(f"  {src.replace('.', '_').replace('-', '_')}[{src}] --> {dst.replace('.', '_').replace('-', '_')}[{dst}]")
    else:
        lines.append("  query[query] --> retrieval[retrieval.strategy]")
        lines.append("  retrieval --> answer[answer.builder]")
    lines.append("```")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to report.json or a direct query-result JSON.")
    parser.add_argument("--out", default="", help="Optional output markdown path.")
    args = parser.parse_args(argv)

    in_path = Path(str(args.input)).resolve()
    payload = _load_json(in_path)
    query_result = _resolve_query_payload(payload)
    if not query_result:
        print(json.dumps({"ok": False, "error": "query_payload_not_found", "input": str(in_path)}))
        return 2

    markdown = _render_markdown(query_result, source_path=str(in_path))
    out_path = Path(str(args.out)).resolve() if str(args.out).strip() else (in_path.parent / "workflow_tree.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
