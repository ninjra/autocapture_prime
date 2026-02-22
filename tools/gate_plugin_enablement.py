#!/usr/bin/env python3
"""Gate: deterministic plugin enablement proof for non-8000 required stack."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from tools.gate_config_matrix import NON8000_DEFAULT_REQUIRED_PLUGIN_IDS
except ModuleNotFoundError:  # pragma: no cover - script execution fallback
    from gate_config_matrix import NON8000_DEFAULT_REQUIRED_PLUGIN_IDS


def _run_cli_json(args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"command_failed:{' '.join(args)}:rc={proc.returncode}:stderr={proc.stderr.strip()}")
    try:
        payload = json.loads(proc.stdout)
    except Exception as exc:  # pragma: no cover - defensive path
        raise RuntimeError(f"invalid_json:{' '.join(args)}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected_payload:{' '.join(args)}")
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid_json_object:{path}")
    return payload


def evaluate_enablement(
    *,
    plugins_list: dict[str, Any],
    load_report: dict[str, Any],
    required_ids: list[str],
) -> dict[str, Any]:
    plugin_rows = plugins_list.get("plugins", []) if isinstance(plugins_list, dict) else []
    by_id = {
        str(item.get("plugin_id") or "").strip(): item
        for item in plugin_rows
        if isinstance(item, dict) and str(item.get("plugin_id") or "").strip()
    }
    report = load_report.get("report", {}) if isinstance(load_report, dict) else {}
    loaded_set = {str(pid).strip() for pid in report.get("loaded", []) if str(pid).strip()} if isinstance(report, dict) else set()
    failed_set = {str(pid).strip() for pid in report.get("failed", []) if str(pid).strip()} if isinstance(report, dict) else set()

    checks: list[dict[str, Any]] = []
    failing: list[dict[str, Any]] = []
    for plugin_id in required_ids:
        row = by_id.get(plugin_id)
        present = row is not None
        allowlisted = bool(row.get("allowlisted")) if isinstance(row, dict) else False
        enabled = bool(row.get("enabled")) if isinstance(row, dict) else False
        hash_ok = bool(row.get("hash_ok")) if isinstance(row, dict) else False
        loaded = plugin_id in loaded_set
        in_failed = plugin_id in failed_set
        reasons: list[str] = []
        if not present:
            reasons.append("missing_from_plugins_list")
        if not allowlisted:
            reasons.append("allowlisted_false")
        if not enabled:
            reasons.append("enabled_false")
        if not hash_ok:
            reasons.append("hash_not_ok")
        if not loaded:
            reasons.append("not_loaded")
        if in_failed:
            reasons.append("in_failed_report")
        ok = len(reasons) == 0
        check = {
            "plugin_id": plugin_id,
            "ok": ok,
            "present": present,
            "allowlisted": allowlisted,
            "enabled": enabled,
            "hash_ok": hash_ok,
            "loaded": loaded,
            "in_failed_report": in_failed,
            "reasons": reasons,
        }
        checks.append(check)
        if not ok:
            failing.append(check)

    return {
        "schema_version": 1,
        "ok": len(failing) == 0,
        "required_count": len(required_ids),
        "failed_count": len(failing),
        "required_ids": required_ids,
        "checks": checks,
        "summary": {
            "loaded_count": len(loaded_set),
            "failed_count_total": len(failed_set),
        },
    }


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate required plugin enablement from plugin list + load-report.")
    parser.add_argument("--plugins-list-json", default="", help="Optional path to cached plugins list payload.")
    parser.add_argument("--load-report-json", default="", help="Optional path to cached load-report payload.")
    parser.add_argument("--required-id", action="append", default=[], help="Additional required plugin ID. Repeatable.")
    parser.add_argument(
        "--output",
        default="artifacts/plugin_enablement/gate_plugin_enablement.json",
        help="Output path for gate artifact JSON.",
    )
    return parser.parse_args()


def main() -> int:
    ns = _args()
    required = sorted({*NON8000_DEFAULT_REQUIRED_PLUGIN_IDS, *[str(pid).strip() for pid in ns.required_id if str(pid).strip()]})
    if ns.plugins_list_json:
        plugins_list = _load_json(Path(ns.plugins_list_json))
    else:
        plugins_list = _run_cli_json([sys.executable, "-m", "autocapture_nx", "plugins", "list", "--json"])
    if ns.load_report_json:
        load_report = _load_json(Path(ns.load_report_json))
    else:
        load_report = _run_cli_json([sys.executable, "-m", "autocapture_nx", "plugins", "load-report"])

    result = evaluate_enablement(plugins_list=plugins_list, load_report=load_report, required_ids=required)
    out = Path(ns.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": bool(result.get("ok", False)),
                "required_count": int(result.get("required_count", 0) or 0),
                "failed_count": int(result.get("failed_count", 0) or 0),
                "output": str(out),
            },
            sort_keys=True,
        )
    )
    return 0 if bool(result.get("ok", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
