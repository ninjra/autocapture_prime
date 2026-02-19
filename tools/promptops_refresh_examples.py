#!/usr/bin/env python3
"""Build PromptOps examples from query traces and metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from autocapture.promptops.examples import build_examples_from_traces, write_examples_file
from autocapture_nx.kernel.config import load_config
from autocapture_nx.kernel.loader import default_config_paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", default="data/facts/query_trace.ndjson", help="Query trace ndjson path.")
    parser.add_argument("--metrics", default="data/promptops/metrics.jsonl", help="PromptOps metrics jsonl path.")
    parser.add_argument("--output", default="", help="Output examples JSON path.")
    parser.add_argument("--max-rows", type=int, default=5000, help="Max rows to scan from each source.")
    args = parser.parse_args(argv)

    config = load_config(default_config_paths(), safe_mode=False)
    promptops = config.get("promptops", {}) if isinstance(config, dict) else {}
    output = str(args.output or promptops.get("examples_path") or "data/promptops/examples.json").strip()

    built = build_examples_from_traces(
        query_trace_path=Path(str(args.trace)),
        metrics_path=Path(str(args.metrics)),
        max_trace_rows=max(100, int(args.max_rows)),
    )
    write_examples_file(
        Path(output),
        examples=built.examples,
        source_counts=built.source_counts,
    )
    summary = {
        "ok": True,
        "output": str(Path(output).resolve()),
        "prompt_ids": sorted(list(built.examples.keys())),
        "counts": {pid: int(len(rows)) for pid, rows in sorted(built.examples.items(), key=lambda kv: kv[0])},
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
