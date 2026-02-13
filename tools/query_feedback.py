#!/usr/bin/env python3
"""Append interactive correctness feedback for query answers."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.hashing import sha256_text
from autocapture_nx.storage.facts_ndjson import append_fact_line


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _config_from_env() -> dict[str, Any]:
    data_dir = os.getenv("AUTOCAPTURE_DATA_DIR", "").strip()
    if not data_dir:
        data_dir = "data"
    return {"storage": {"data_dir": str(Path(data_dir).expanduser().absolute())}}


def _facts_file(config: dict[str, Any], rel_name: str) -> Path:
    storage = config.get("storage", {}) if isinstance(config, dict) else {}
    data_dir = storage.get("data_dir", "data") if isinstance(storage, dict) else "data"
    root = Path(str(data_dir))
    facts_dir = storage.get("facts_dir", "facts") if isinstance(storage, dict) else "facts"
    return root / str(facts_dir) / rel_name


def _latest_trace(config: dict[str, Any]) -> dict[str, Any]:
    path = _facts_file(config, "query_trace.ndjson")
    if not path.exists():
        return {}
    latest: dict[str, Any] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = str(raw or "").strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                latest = item
    return latest


def _score_from_verdict(verdict: str) -> float:
    low = str(verdict or "").strip().casefold()
    if low in {"agree", "correct", "yes", "y", "true"}:
        return 1.0
    if low in {"disagree", "incorrect", "no", "n", "false"}:
        return 0.0
    if low in {"partial", "partially_correct"}:
        return 0.5
    return -1.0


def _parse_score(value: str) -> float:
    text = str(value or "").strip().lower()
    inferred = _score_from_verdict(text)
    if inferred >= 0.0:
        return inferred
    try:
        num = float(text)
    except Exception:
        raise ValueError("score must be agree/disagree/partial or numeric [0,1]")
    return max(0.0, min(1.0, num))


def _split_list(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for raw in values or []:
        for item in str(raw or "").split(","):
            val = str(item or "").strip()
            if val:
                out.append(val)
    return sorted(set(out))


def append_feedback(
    *,
    config: dict[str, Any],
    query: str,
    query_run_id: str,
    score: float,
    verdict: str,
    notes: str,
    method: str,
    expected_answer: str,
    actual_answer: str,
    plugin_fix_summary: str,
    plugin_fix_files: list[str],
    plugin_ids: list[str],
    feedback_source: str,
) -> dict[str, Any]:
    payload = {
        "schema_version": 2,
        "record_type": "derived.eval.feedback",
        "ts_utc": _utc(),
        "query_run_id": str(query_run_id or ""),
        "query": str(query or ""),
        "query_sha256": sha256_text(str(query or "")),
        "score_bp": int(round(float(score) * 10000.0)),
        "label": "correct" if score >= 0.5 else "incorrect",
        "verdict": str(verdict or ""),
        "notes": str(notes or ""),
        "method": str(method or ""),
        "expected_answer": str(expected_answer or ""),
        "actual_answer": str(actual_answer or ""),
        "plugin_fix_summary": str(plugin_fix_summary or ""),
        "plugin_fix_files": list(plugin_fix_files),
        "plugin_ids": list(plugin_ids),
        "feedback_source": str(feedback_source or ""),
    }
    res = append_fact_line(config, rel_path="query_feedback.ndjson", payload=payload)
    return {"ok": bool(res.ok), "path": res.path, "error": res.error, "payload": payload}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="", help="Original query text.")
    parser.add_argument("--query-run-id", default="", help="Explicit query_run_id (defaults to latest trace record).")
    parser.add_argument("--score", default="", help="agree/disagree/partial or number in [0,1].")
    parser.add_argument("--verdict", default="", help="agree/disagree/partial (used when --score omitted).")
    parser.add_argument("--notes", default="", help="Optional reviewer notes.")
    parser.add_argument("--method", default="", help="Optional method label (classic/state/synth/etc).")
    parser.add_argument("--expected-answer", default="", help="Ground-truth answer text from reviewer.")
    parser.add_argument("--actual-answer", default="", help="Observed answer text to compare against.")
    parser.add_argument("--plugin-fix-summary", default="", help="How plugin workflow should be adjusted.")
    parser.add_argument("--plugin-fix-file", action="append", default=[], help="File(s) changed or expected to change.")
    parser.add_argument("--plugin-id", action="append", default=[], help="Plugin ids involved in this correction.")
    parser.add_argument("--feedback-source", default="manual", help="feedback source: manual/interactive/ci")
    args = parser.parse_args(argv)

    cfg = _config_from_env()
    latest = _latest_trace(cfg)
    query = str(args.query or "").strip() or str(latest.get("query") or "").strip()
    query_run_id = str(args.query_run_id or "").strip() or str(latest.get("query_run_id") or "").strip()
    if not query:
        print("ERROR: query is required (or query_trace.ndjson must contain a recent query).")
        return 2
    if not query_run_id:
        print("ERROR: query_run_id is required (or query_trace.ndjson must contain one).")
        return 2

    score_text = str(args.score or "").strip()
    verdict_text = str(args.verdict or "").strip()
    if not score_text and verdict_text:
        score_text = verdict_text
    if not score_text:
        score_text = "0.5"
    try:
        score = _parse_score(score_text)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2
    if not verdict_text:
        verdict_text = "agree" if score >= 0.75 else ("disagree" if score <= 0.25 else "partial")

    plugin_fix_files = _split_list(list(args.plugin_fix_file or []))
    plugin_ids = _split_list(list(args.plugin_id or []))
    result = append_feedback(
        config=cfg,
        query=query,
        query_run_id=query_run_id,
        score=score,
        verdict=verdict_text,
        notes=str(args.notes or ""),
        method=str(args.method or ""),
        expected_answer=str(args.expected_answer or ""),
        actual_answer=str(args.actual_answer or ""),
        plugin_fix_summary=str(args.plugin_fix_summary or ""),
        plugin_fix_files=plugin_fix_files,
        plugin_ids=plugin_ids,
        feedback_source=str(args.feedback_source or "manual"),
    )
    out = {"ok": bool(result.get("ok")), "path": result.get("path"), "error": result.get("error")}
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if bool(result.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
