#!/usr/bin/env python3
"""Gate: PromptOps policy, localhost safety, and lockfile coverage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from autocapture_nx.kernel.config import load_config
from autocapture_nx.kernel.loader import default_config_paths


REQUIRED_PLUGIN_IDS = [
    "builtin.prompt.bundle.default",
    "builtin.processing.sst.pipeline",
    "builtin.processing.sst.ui_vlm",
    "builtin.screen.parse.v1",
    "builtin.screen.index.v1",
    "builtin.screen.answer.v1",
]


def _is_non8000_mode(config: dict[str, Any]) -> bool:
    plugins = config.get("plugins", {}) if isinstance(config, dict) else {}
    enabled = plugins.get("enabled", {}) if isinstance(plugins, dict) else {}
    processing = config.get("processing", {}) if isinstance(config, dict) else {}
    idle = processing.get("idle", {}) if isinstance(processing, dict) else {}
    idle_extractors = idle.get("extractors", {}) if isinstance(idle, dict) else {}
    sst = processing.get("sst", {}) if isinstance(processing, dict) else {}
    ui_vlm_cfg = sst.get("ui_vlm", {}) if isinstance(sst, dict) else {}
    return (
        not bool(enabled.get("builtin.vlm.vllm_localhost", False))
        and not bool(enabled.get("builtin.processing.sst.ui_vlm", False))
        and not bool(idle_extractors.get("vlm", False))
        and not bool(ui_vlm_cfg.get("enabled", False))
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_promptops_policy(
    config: dict[str, Any],
    lock_payload: dict[str, Any],
    safe_mode_config: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    plugins = config.get("plugins", {}) if isinstance(config, dict) else {}
    promptops = config.get("promptops", {}) if isinstance(config, dict) else {}
    allowlist = plugins.get("allowlist", []) if isinstance(plugins, dict) else []
    enabled = plugins.get("enabled", {}) if isinstance(plugins, dict) else {}
    locks_map = lock_payload.get("plugins", {}) if isinstance(lock_payload, dict) else {}
    non8000_mode = _is_non8000_mode(config)
    review = promptops.get("review", {}) if isinstance(promptops, dict) else {}
    optimizer = promptops.get("optimizer", {}) if isinstance(promptops, dict) else {}
    review_base = str(review.get("base_url") or "").strip()
    parsed = urlparse(review_base) if review_base else None
    is_local_review = False
    if parsed is not None:
        is_local_review = parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost"}

    checks.append({"name": "allowlist_non_empty", "ok": isinstance(allowlist, list) and len(allowlist) > 0})
    checks.append({"name": "promptops_enabled", "ok": bool(promptops.get("enabled", False))})
    checks.append({"name": "promptops_require_citations", "ok": bool(promptops.get("require_citations", False))})
    checks.append(
        {
            "name": "promptops_examples_path_set",
            "ok": bool(str(promptops.get("examples_path") or "").strip()),
        }
    )
    query_strategy = str(promptops.get("query_strategy") or "").strip().lower()
    model_strategy = str(promptops.get("model_strategy") or "").strip().lower()
    checks.append(
        {
            "name": "promptops_query_strategy_non_none",
            "ok": query_strategy not in {"", "none", "off", "disabled"},
            "value": query_strategy,
        }
    )
    checks.append(
        {
            "name": "promptops_model_strategy_non_none",
            "ok": model_strategy not in {"", "none", "off", "disabled"},
            "value": model_strategy,
        }
    )
    checks.append(
        {
            "name": "promptops_persist_query_prompts",
            "ok": bool(promptops.get("persist_query_prompts", False)),
        }
    )
    checks.append(
        {
            "name": "promptops_require_query_path",
            "ok": bool(promptops.get("require_query_path", False)),
        }
    )
    checks.append(
        {
            "name": "promptops_review_require_preflight",
            "ok": bool(review.get("require_preflight", False)),
        }
    )
    optimizer_strategies = optimizer.get("strategies", []) if isinstance(optimizer, dict) else []
    checks.append(
        {
            "name": "promptops_optimizer_enabled",
            "ok": bool(optimizer.get("enabled", False)),
        }
    )
    checks.append(
        {
            "name": "promptops_optimizer_has_strategies",
            "ok": isinstance(optimizer_strategies, list) and len(optimizer_strategies) > 0,
        }
    )
    checks.append(
        {
            "name": "promptops_optimizer_interval_positive",
            "ok": float(optimizer.get("interval_s", 0) or 0) > 0,
        }
    )
    checks.append(
        {
            "name": "promptops_optimizer_refresh_examples",
            "ok": bool(optimizer.get("refresh_examples", False)),
        }
    )
    checks.append({"name": "review_base_url_localhost", "ok": bool(is_local_review), "value": review_base})

    for plugin_id in REQUIRED_PLUGIN_IDS:
        checks.append(
            {
                "name": f"allowlist_contains:{plugin_id}",
                "ok": plugin_id in allowlist,
            }
        )
        if plugin_id == "builtin.processing.sst.ui_vlm":
            expected_enabled = not non8000_mode
            checks.append(
                {
                    "name": f"enabled_matches_mode:{plugin_id}",
                    "ok": bool(enabled.get(plugin_id, False)) == bool(expected_enabled),
                    "expected": bool(expected_enabled),
                    "value": bool(enabled.get(plugin_id, False)),
                }
            )
        else:
            checks.append(
                {
                    "name": f"enabled_contains:{plugin_id}",
                    "ok": bool(enabled.get(plugin_id, False)),
                }
            )
        checks.append(
            {
                "name": f"lock_contains:{plugin_id}",
                "ok": plugin_id in locks_map,
            }
        )

    safe_plugins = safe_mode_config.get("plugins", {}) if isinstance(safe_mode_config, dict) else {}
    checks.append({"name": "safe_mode_forces_plugins_safe_mode", "ok": bool(safe_plugins.get("safe_mode", False))})
    return checks


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    default_cfg = _load_json(root / "config" / "default.json")
    lock_payload = _load_json(root / "config" / "plugin_locks.json")
    safe_cfg = load_config(default_config_paths(), safe_mode=True)
    checks = validate_promptops_policy(default_cfg, lock_payload, safe_cfg)
    ok = all(bool(item.get("ok", False)) for item in checks)

    out = root / "artifacts" / "promptops" / "gate_promptops_policy.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ok": bool(ok),
                "checks": checks,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    if ok:
        print("OK: promptops policy gate")
        return 0
    print("FAIL: promptops policy gate")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
