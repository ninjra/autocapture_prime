from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{2,}")


def _tokens(text: str) -> list[str]:
    return [tok.lower() for tok in TOKEN_RE.findall(text or "")]


def build_lexical_index(rows: list[dict[str, Any]], out_path: Path) -> Path:
    posting: dict[str, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        content = " ".join(str(row.get(key) or "") for key in ("text", "label", "type"))
        seen: set[str] = set()
        for tok in _tokens(content):
            if tok in seen:
                continue
            posting[tok].append(idx)
            seen.add(tok)
    payload = {k: v for k, v in sorted(posting.items())}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return out_path


def search_lexical_index(index_path: Path, rows: list[dict[str, Any]], query: str, top_k: int = 5) -> list[dict[str, Any]]:
    if not index_path.exists():
        return []
    posting = json.loads(index_path.read_text(encoding="utf-8"))
    scores: dict[int, int] = defaultdict(int)
    for tok in _tokens(query):
        for idx in posting.get(tok, []):
            scores[int(idx)] += 1
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    output: list[dict[str, Any]] = []
    for idx, _ in ranked[: max(1, top_k)]:
        if 0 <= idx < len(rows):
            output.append(rows[idx])
    return output
