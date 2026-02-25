#!/usr/bin/env python3
"""Gate: deterministic plugin enablement proof for non-8000 required stack."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from collections import defaultdict
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


def _stage_bucket_for_plugin(row: dict[str, Any]) -> str:
    plugin_id = str(row.get("plugin_id") or "").strip().casefold()
    kinds = [str(item).strip().casefold() for item in row.get("kinds", []) if str(item).strip()] if isinstance(row.get("kinds"), list) else []
    provides = [str(item).strip().casefold() for item in row.get("provides", []) if str(item).strip()] if isinstance(row.get("provides"), list) else []
    text = " ".join([plugin_id, *kinds, *provides])
    if (
        ".capture." in plugin_id
        or "capture." in text
        or "tracking." in text
        or "window.metadata" in text
    ):
        return "stage1_capture"
    if (
        ".sst." in plugin_id
        or ".state." in plugin_id
        or "processing.stage.hooks" in text
        or "processing.pipeline" in text
        or "state." in text
    ):
        return "stage2_plus"
    if (
        ".retrieval." in plugin_id
        or ".answer." in plugin_id
        or "retrieval.strategy" in text
        or "answer.builder" in text
        or "screen.answer.v1" in text
        or "time.intent_parser" in text
        or "citation.validator" in text
        or "reranker" in text
    ):
        return "query_runtime"
    if (
        ".storage." in plugin_id
        or "storage." in text
        or "journal.writer" in text
        or "ledger.writer" in text
        or "observability" in text
    ):
        return "core_runtime"
    return "other"


def _plugin_coverage(
    *,
    plugin_rows: list[dict[str, Any]],
    loaded_set: set[str],
    failed_set: set[str],
    skipped_set: set[str],
) -> dict[str, Any]:
    by_stage: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "plugins": 0,
            "enabled": 0,
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "enabled_unattempted": 0,
        }
    )
    totals = {
        "plugins": 0,
        "enabled": 0,
        "attempted": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "enabled_unattempted": 0,
    }
    for row in plugin_rows:
        if not isinstance(row, dict):
            continue
        plugin_id = str(row.get("plugin_id") or "").strip()
        if not plugin_id:
            continue
        enabled = bool(row.get("enabled"))
        succeeded = plugin_id in loaded_set
        failed = plugin_id in failed_set
        skipped = plugin_id in skipped_set
        attempted = bool(succeeded or failed or skipped)
        enabled_unattempted = bool(enabled and not attempted)
        stage = _stage_bucket_for_plugin(row)
        counters = by_stage[stage]
        counters["plugins"] += 1
        totals["plugins"] += 1
        if enabled:
            counters["enabled"] += 1
            totals["enabled"] += 1
        if attempted:
            counters["attempted"] += 1
            totals["attempted"] += 1
        if succeeded:
            counters["succeeded"] += 1
            totals["succeeded"] += 1
        if failed:
            counters["failed"] += 1
            totals["failed"] += 1
        if skipped:
            counters["skipped"] += 1
            totals["skipped"] += 1
        if enabled_unattempted:
            counters["enabled_unattempted"] += 1
            totals["enabled_unattempted"] += 1
    return {
        "by_stage": {stage: dict(counters) for stage, counters in sorted(by_stage.items())},
        "totals": totals,
    }


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
    skipped_set = {str(pid).strip() for pid in report.get("skipped", []) if str(pid).strip()} if isinstance(report, dict) else set()
    coverage = _plugin_coverage(plugin_rows=plugin_rows, loaded_set=loaded_set, failed_set=failed_set, skipped_set=skipped_set)

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
        "plugin_coverage": coverage,
        "summary": {
            "loaded_count": len(loaded_set),
            "failed_count_total": len(failed_set),
            "skipped_count_total": len(skipped_set),
            "coverage_totals": coverage.get("totals", {}),
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
