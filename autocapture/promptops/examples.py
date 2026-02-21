"""PromptOps example-set builders and loaders."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_STOPWORDS = {
    "the",
    "and",
    "that",
    "this",
    "with",
    "from",
    "have",
    "what",
    "when",
    "where",
    "which",
    "your",
    "about",
    "would",
    "could",
    "should",
    "there",
    "their",
    "they",
    "them",
    "into",
    "over",
    "under",
    "while",
    "who",
    "how",
    "many",
    "open",
}


def _normalize_prompt_id(prompt_id: str) -> str:
    pid = str(prompt_id or "").strip()
    if pid == "query":
        return "query.default"
    return pid


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_examples_file(path: Path, *, prompt_id: str) -> list[dict[str, Any]]:
    payload = _load_json(path)
    root = payload.get("promptops_examples")
    if not isinstance(root, dict):
        root = payload
    pid = _normalize_prompt_id(prompt_id)
    aliases = [pid]
    if pid == "query.default":
        aliases.append("query")
    elif pid == "query":
        aliases.append("query.default")
    out: list[dict[str, Any]] = []
    for key in aliases:
        value = root.get(key)
        if isinstance(value, list):
            out.extend([row for row in value if isinstance(row, dict)])
    return out


def _keywords(text: str, *, limit: int = 3) -> list[str]:
    words = []
    for token in _WORD_RE.findall(str(text or "").lower()):
        tok = token.strip().lower()
        if len(tok) < 4:
            continue
        if tok in _STOPWORDS:
            continue
        words.append(tok)
    dedup: list[str] = []
    seen: set[str] = set()
    for word in words:
        if word in seen:
            continue
        seen.add(word)
        dedup.append(word)
        if len(dedup) >= max(1, int(limit)):
            break
    return dedup


def _load_ndjson(path: Path, *, max_rows: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    for line in lines[-max(1, int(max_rows)) :]:
        raw = str(line or "").strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


@dataclass(frozen=True)
class ExampleBuildResult:
    examples: dict[str, list[dict[str, Any]]]
    source_counts: dict[str, int]


def build_examples_from_traces(
    *,
    query_trace_path: Path,
    metrics_path: Path,
    max_trace_rows: int = 5000,
) -> ExampleBuildResult:
    traces = _load_ndjson(query_trace_path, max_rows=max_trace_rows)
    metrics = _load_ndjson(metrics_path, max_rows=max_trace_rows)
    out: dict[str, list[dict[str, Any]]] = {}
    source_counts: dict[str, int] = {}

    def _add(prompt_id: str, row: dict[str, Any]) -> None:
        pid = _normalize_prompt_id(prompt_id)
        out.setdefault(pid, []).append(row)
        source_counts[pid] = int(source_counts.get(pid, 0) + 1)

    # Query/state examples from real query traces.
    seen_query: set[str] = set()
    for row in traces:
        query = str(row.get("query_effective") or row.get("query") or "").strip()
        if not query:
            continue
        qhash = str(row.get("query_sha256") or "").strip() or query.lower()
        if qhash in seen_query:
            continue
        seen_query.add(qhash)
        words = _keywords(query, limit=3)
        if not words:
            continue
        ex = {
            "required_tokens": words,
            "requires_citation": False,
            "source": "query_trace",
            "query_sha256": qhash,
        }
        _add("query.default", ex)
        _add("state_query", ex)

    # Hard VLM prompts need at least structural policy checks.
    hard_prompt_ids: set[str] = set()
    for row in metrics:
        if str(row.get("type") or "") != "promptops.model_interaction":
            continue
        pid = str(row.get("prompt_id") or "").strip()
        if pid.startswith("hard_vlm."):
            hard_prompt_ids.add(pid)
    for pid in sorted(hard_prompt_ids):
        _add(
            pid,
            {
                "required_tokens": ["Answer", "policy"],
                "requires_citation": False,
                "source": "metrics_hard_vlm",
            },
        )

    # Deduplicate examples per prompt id by token signature.
    dedup: dict[str, list[dict[str, Any]]] = {}
    for pid, rows in out.items():
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        for row in rows:
            toks = row.get("required_tokens", [])
            key = "|".join(sorted([str(tok).lower() for tok in toks if str(tok).strip()]))
            if not key or key in seen:
                continue
            seen.add(key)
            items.append(dict(row))
        dedup[pid] = items

    return ExampleBuildResult(examples=dedup, source_counts=source_counts)


def write_examples_file(
    path: Path,
    *,
    examples: dict[str, list[dict[str, Any]]],
    source_counts: dict[str, int] | None = None,
) -> None:
    payload = {
        "schema_version": 1,
        "promptops_examples": {k: v for k, v in sorted(examples.items(), key=lambda kv: kv[0])},
    }
    if isinstance(source_counts, dict):
        payload["source_counts"] = {k: int(v) for k, v in sorted(source_counts.items(), key=lambda kv: kv[0])}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
