#!/usr/bin/env python3
"""Gate: configuration matrix coherence for golden runtime profile."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from autocapture_nx.kernel.config import load_config
from autocapture_nx.kernel.loader import default_config_paths
from autocapture_nx.inference.vllm_endpoint import EXTERNAL_VLLM_EXPECTED_MODEL


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_local_v1_url(url: str) -> bool:
    raw = str(url or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    path = str(parsed.path or "").rstrip("/")
    return (
        str(parsed.scheme or "").lower() == "http"
        and str(parsed.hostname or "") in {"127.0.0.1", "localhost"}
        and path == "/v1"
    )


def validate_config_matrix(default_cfg: dict[str, Any], safe_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    promptops = default_cfg.get("promptops", {}) if isinstance(default_cfg, dict) else {}
    optimizer = promptops.get("optimizer", {}) if isinstance(promptops, dict) else {}
    review = promptops.get("review", {}) if isinstance(promptops, dict) else {}
    research = default_cfg.get("research", {}) if isinstance(default_cfg, dict) else {}
    plugins = default_cfg.get("plugins", {}) if isinstance(default_cfg, dict) else {}
    enabled = plugins.get("enabled", {}) if isinstance(plugins, dict) else {}
    safe_plugins = safe_cfg.get("plugins", {}) if isinstance(safe_cfg, dict) else {}

    checks.append({"name": "promptops_enabled", "ok": bool(promptops.get("enabled", False))})
    checks.append({"name": "promptops_require_citations", "ok": bool(promptops.get("require_citations", False))})
    checks.append(
        {
            "name": "promptops_examples_path_set",
            "ok": bool(str(promptops.get("examples_path") or "").strip()),
            "value": str(promptops.get("examples_path") or ""),
        }
    )
    checks.append({"name": "promptops_require_query_path", "ok": bool(promptops.get("require_query_path", False))})
    query_strategy = str(promptops.get("query_strategy") or "").strip().lower()
    checks.append({"name": "promptops_query_strategy_non_none", "ok": query_strategy not in {"", "none", "off", "disabled"}, "value": query_strategy})
    checks.append({"name": "promptops_review_base_url_local_v1", "ok": _is_local_v1_url(str(review.get("base_url") or "")), "value": str(review.get("base_url") or "")})
    checks.append(
        {
            "name": "promptops_review_model_matches_expected",
            "ok": str(review.get("model") or "").strip() == EXTERNAL_VLLM_EXPECTED_MODEL,
            "value": str(review.get("model") or ""),
            "expected": EXTERNAL_VLLM_EXPECTED_MODEL,
        }
    )
    checks.append({"name": "promptops_optimizer_enabled", "ok": bool(optimizer.get("enabled", False))})
    checks.append(
        {
            "name": "promptops_optimizer_interval_positive",
            "ok": float(optimizer.get("interval_s", 0) or 0) > 0,
            "value": float(optimizer.get("interval_s", 0) or 0),
        }
    )
    strategies = optimizer.get("strategies", []) if isinstance(optimizer, dict) else []
    checks.append(
        {
            "name": "promptops_optimizer_has_strategies",
            "ok": isinstance(strategies, list) and len(strategies) > 0,
            "value": list(strategies) if isinstance(strategies, list) else [],
        }
    )
    checks.append(
        {
            "name": "promptops_optimizer_refresh_examples",
            "ok": bool(optimizer.get("refresh_examples", False)),
        }
    )

    checks.append({"name": "research_disabled_in_prime", "ok": not bool(research.get("enabled", True))})
    checks.append({"name": "research_owner_hypervisor", "ok": str(research.get("owner") or "").strip() == "hypervisor"})
    checks.append({"name": "research_plugin_disabled", "ok": not bool(enabled.get("builtin.research.default", True))})

    checks.append({"name": "safe_mode_forced_in_safe_cfg", "ok": bool(safe_plugins.get("safe_mode", False))})
    return checks


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    default_cfg = _load_json(root / "config" / "default.json")
    safe_cfg = load_config(default_config_paths(), safe_mode=True)
    checks = validate_config_matrix(default_cfg, safe_cfg)
    ok = all(bool(item.get("ok", False)) for item in checks)
    out = root / "artifacts" / "config" / "gate_config_matrix.json"
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
    print(json.dumps({"ok": bool(ok), "output": str(out)}, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
