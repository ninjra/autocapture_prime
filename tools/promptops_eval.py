"""Run template-level PromptOps evaluation cases."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from autocapture.promptops.harness import load_eval_cases, run_template_eval
from autocapture_nx.kernel.config import ConfigPaths, load_config
from autocapture_nx.kernel.loader import default_config_paths
from autocapture_nx.kernel.paths import resolve_repo_path


def _config_paths(config_dir: str | None) -> ConfigPaths:
    if not config_dir:
        return default_config_paths()
    root = Path(config_dir)
    return ConfigPaths(
        default_path=resolve_repo_path("config/default.json"),
        user_path=(root / "user.json").resolve(),
        schema_path=resolve_repo_path("contracts/config_schema.json"),
        backup_dir=(root / "backup").resolve(),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", help="Path to promptops eval cases JSON")
    parser.add_argument("--output", help="Output report path")
    parser.add_argument("--config-dir", help="Config directory (contains user.json)")
    parser.add_argument("--include-prompt", action="store_true", help="Include resolved prompt text in report")
    parser.add_argument("--include-sources", action="store_true", help="Include resolved sources in report")
    parser.add_argument("--safe-mode", action="store_true", help="Load config in safe mode")
    args = parser.parse_args()

    paths = _config_paths(args.config_dir)
    config = load_config(paths, safe_mode=bool(args.safe_mode))
    eval_cfg = config.get("promptops", {}).get("eval", {}) if isinstance(config, dict) else {}
    cases_path = args.cases or (eval_cfg.get("cases_path") if isinstance(eval_cfg, dict) else None)
    if not cases_path:
        raise SystemExit("promptops eval cases path is required (use --cases or promptops.eval.cases_path)")
    output_path = args.output or (eval_cfg.get("output_path") if isinstance(eval_cfg, dict) else None) or "artifacts/promptops_eval.json"
    include_prompt = bool(args.include_prompt) or bool(eval_cfg.get("include_prompt", False))
    include_sources = bool(args.include_sources) or bool(eval_cfg.get("include_sources", False))

    cases = load_eval_cases(cases_path)
    report = run_template_eval(
        config,
        cases,
        include_prompt=include_prompt,
        include_sources=include_sources,
    )

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    return 0 if int(report.get("summary", {}).get("failed", 0)) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
