#!/usr/bin/env python3
"""Run one PromptOps optimizer cycle and persist report."""

from __future__ import annotations

import argparse
import json

from autocapture.promptops.optimizer import PromptOpsOptimizer
from autocapture_nx.kernel.config import load_config
from autocapture_nx.kernel.loader import default_config_paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Run even if interval says not due.")
    parser.add_argument("--user-active", action="store_true", help="Simulate active user state.")
    parser.add_argument("--idle-seconds", type=float, default=60.0, help="Idle seconds context for the run.")
    args = parser.parse_args(argv)

    config = load_config(default_config_paths(), safe_mode=False)
    optimizer = PromptOpsOptimizer(config)
    report = optimizer.run_once(
        user_active=bool(args.user_active),
        idle_seconds=float(args.idle_seconds),
        force=bool(args.force),
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
