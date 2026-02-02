"""Run deterministic state-layer evaluation on golden fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from autocapture_nx.kernel.config import load_config
from autocapture_nx.kernel.loader import default_config_paths
from autocapture_nx.state_layer.harness import load_state_eval_cases, run_state_eval


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="tests/fixtures/state_golden.json")
    parser.add_argument("--output", default="artifacts/state_layer_eval.json")
    args = parser.parse_args(argv)

    config = load_config(default_config_paths(), safe_mode=True)
    payload = load_state_eval_cases(args.cases)
    result = run_state_eval(config, cases=payload["cases"], states=payload["states"])

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if not result.get("ok"):
        print("FAIL: state layer eval")
        return 1
    print("OK: state layer eval")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
