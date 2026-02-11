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


def _parse_score(value: str) -> float:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "correct", "yes", "y"}:
        return 1.0
    if text in {"0", "false", "incorrect", "no", "n"}:
        return 0.0
    try:
        num = float(text)
    except Exception:
        raise ValueError("score must be true/false/correct/incorrect or numeric [0,1]")
    return max(0.0, min(1.0, num))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True, help="Original query text.")
    parser.add_argument("--score", required=True, help="correct/incorrect or number in [0,1].")
    parser.add_argument("--notes", default="", help="Optional reviewer notes.")
    parser.add_argument("--method", default="", help="Optional method label (classic/state/synth/etc).")
    args = parser.parse_args(argv)

    try:
        score = _parse_score(args.score)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2

    query = str(args.query or "")
    payload = {
        "schema_version": 1,
        "record_type": "derived.eval.feedback",
        "ts_utc": _utc(),
        "query": query,
        "query_sha256": sha256_text(query),
        "score_bp": int(round(float(score) * 10000.0)),
        "label": "correct" if score >= 0.5 else "incorrect",
        "notes": str(args.notes or ""),
        "method": str(args.method or ""),
    }
    cfg = _config_from_env()
    res = append_fact_line(cfg, rel_path="query_feedback.ndjson", payload=payload)
    out = {"ok": bool(res.ok), "path": res.path, "error": res.error}
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
