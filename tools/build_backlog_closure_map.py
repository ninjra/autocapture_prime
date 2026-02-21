#!/usr/bin/env python3
"""Build deterministic closure crosswalk for tracked backlog rows."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _row_key(row: dict[str, Any]) -> str:
    source = str(row.get("source_path") or "").strip()
    line = int(row.get("line", 0) or 0)
    snippet = str(row.get("snippet") or "").strip()
    digest = hashlib.sha256(snippet.encode("utf-8")).hexdigest()[:16]
    return f"{source}:{line}:{digest}"


def _entry_for_row(row: dict[str, Any]) -> dict[str, Any]:
    source = str(row.get("source_path") or "")
    line = int(row.get("line", 0) or 0)
    key = (source, line)
    mapping: dict[tuple[str, int], dict[str, Any]] = {
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 97): {
            "closure_artifacts": ["artifacts/promptops/metrics_report_latest.json"],
            "closure_command": ".venv/bin/python tools/promptops_metrics_report.py",
            "expected_signal": "\"ok\": true",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 98): {
            "closure_artifacts": ["artifacts/promptops/metrics_report_latest.json"],
            "closure_command": ".venv/bin/python tools/promptops_metrics_report.py",
            "expected_signal": "\"type_counts\"",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 99): {
            "closure_artifacts": ["artifacts/advanced10/question_validation_plugin_trace_latest.json"],
            "closure_command": ".venv/bin/python tools/generate_qh_plugin_validation_report.py",
            "expected_signal": "\"schema_version\": 1",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 133): {
            "closure_artifacts": ["tests/test_promptops_layer.py", "autocapture/promptops/service.py"],
            "closure_command": ".venv/bin/python -m pytest -q tests/test_promptops_layer.py tests/test_promptops_service.py",
            "expected_signal": "pass",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 134): {
            "closure_artifacts": ["artifacts/perf/gate_promptops_perf.json"],
            "closure_command": ".venv/bin/python tools/gate_promptops_perf.py",
            "expected_signal": "\"ok\": true",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 135): {
            "closure_artifacts": ["artifacts/advanced10/question_validation_plugin_trace_latest.json"],
            "closure_command": ".venv/bin/python tools/generate_qh_plugin_validation_report.py",
            "expected_signal": "\"strict_pass_count\"",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 169): {
            "closure_artifacts": ["docs/reports/question-validation-plugin-trace-2026-02-13.md"],
            "closure_command": ".venv/bin/python tools/generate_qh_plugin_validation_report.py",
            "expected_signal": "Plugin Path Contribution Matrix",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 170): {
            "closure_artifacts": ["docs/reports/question-validation-plugin-trace-2026-02-13.md"],
            "closure_command": ".venv/bin/python tools/generate_qh_plugin_validation_report.py",
            "expected_signal": "Strict pass/fail only counted from expected_eval",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 171): {
            "closure_artifacts": ["artifacts/advanced10/question_validation_plugin_trace_latest.json"],
            "closure_command": ".venv/bin/python tools/generate_qh_plugin_validation_report.py",
            "expected_signal": "\"class_rows\"",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 205): {
            "closure_artifacts": ["artifacts/promptops/gate_promptops_policy.json"],
            "closure_command": ".venv/bin/python tools/gate_promptops_policy.py",
            "expected_signal": "\"review_base_url_localhost\"",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 206): {
            "closure_artifacts": ["config/default.json", "tests/test_query_citations_required.py"],
            "closure_command": ".venv/bin/python -m pytest -q tests/test_query_citations_required.py",
            "expected_signal": "pass",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 207): {
            "closure_artifacts": ["artifacts/promptops/gate_promptops_policy.json", "tools/gate_promptops_policy.py"],
            "closure_command": ".venv/bin/python tools/gate_promptops_policy.py",
            "expected_signal": "\"safe_mode_forces_plugins_safe_mode\"",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 241): {
            "closure_artifacts": ["config/profiles/golden_full.json", "tests/test_golden_full_profile_lock.py"],
            "closure_command": ".venv/bin/python -m pytest -q tests/test_golden_full_profile_lock.py",
            "expected_signal": "pass",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 242): {
            "closure_artifacts": ["artifacts/advanced10/question_validation_plugin_trace_latest.json"],
            "closure_command": ".venv/bin/python tools/generate_qh_plugin_validation_report.py",
            "expected_signal": "\"in_path_count\"",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 243): {
            "closure_artifacts": ["docs/runbooks/promptops_golden_ops.md"],
            "closure_command": "test -f docs/runbooks/promptops_golden_ops.md",
            "expected_signal": "exists",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 277): {
            "closure_artifacts": ["artifacts/phaseA/gate_screen_schema.json", "docs/reports/implementation_matrix.md"],
            "closure_command": ".venv/bin/python tools/gate_screen_schema.py",
            "expected_signal": "\"ok\": true",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 278): {
            "closure_artifacts": ["artifacts/phaseA/gate_screen_schema.json"],
            "closure_command": ".venv/bin/python tools/gate_screen_schema.py",
            "expected_signal": "\"schema_version\"",
        },
        ("docs/plans/promptops-four-pillars-improvement-plan.md", 279): {
            "closure_artifacts": ["artifacts/promptops/gate_promptops_policy.json"],
            "closure_command": ".venv/bin/python tools/gate_promptops_policy.py",
            "expected_signal": "\"allowlist_contains:builtin.screen.parse.v1\"",
        },
        ("docs/reports/autocapture_prime_codex_implementation_matrix.md", 24): {
            "closure_artifacts": ["artifacts/live_stack/validation_latest.json"],
            "closure_command": "bash tools/validate_live_chronicle_stack.sh",
            "expected_signal": "\"ok\": true",
        },
    }
    payload = mapping.get(key, {})
    return {
        "row_key": _row_key(row),
        "source_path": source,
        "line": line,
        "snippet": str(row.get("snippet") or ""),
        "category": str(row.get("category") or ""),
        "closure_artifacts": list(payload.get("closure_artifacts") or []),
        "closure_command": str(payload.get("closure_command") or ""),
        "expected_signal": str(payload.get("expected_signal") or ""),
    }


def _render_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Backlog Closure Map (2026-02-16)",
        "",
        "Generated from `artifacts/repo_miss_inventory/latest.json`.",
        "",
        "| Row Key | Source | Closure Artifacts | Closure Command | Expected Signal |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        source = f"{row['source_path']}:{row['line']}"
        artifacts = ", ".join(f"`{p}`" for p in row.get("closure_artifacts", []))
        lines.append(
            f"| `{row['row_key']}` | `{source}` | {artifacts} | `{row.get('closure_command','')}` | `{row.get('expected_signal','')}` |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", default="artifacts/repo_miss_inventory/latest.json")
    parser.add_argument("--output-json", default="artifacts/repo_miss_inventory/backlog_closure_map_latest.json")
    parser.add_argument("--output-md", default="docs/reports/backlog_closure_map_2026-02-16.md")
    parser.add_argument("--baseline-json", default="artifacts/repo_miss_inventory/backlog_rows_baseline_2026-02-16.json")
    args = parser.parse_args(argv)

    inv = json.loads((ROOT / str(args.inventory)).read_text(encoding="utf-8"))
    src_rows = inv.get("rows", []) if isinstance(inv, dict) else []
    rows = [_entry_for_row(row) for row in src_rows if isinstance(row, dict)]
    payload = {
        "schema_version": 1,
        "generated_utc": _utc_now(),
        "inventory": str(args.inventory),
        "rows_total": len(rows),
        "rows": rows,
    }

    out_json = ROOT / str(args.output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    out_md = ROOT / str(args.output_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(_render_markdown(rows), encoding="utf-8")

    baseline = {
        "schema_version": 1,
        "generated_utc": _utc_now(),
        "rows_total": len(rows),
        "row_keys": [str(row.get("row_key") or "") for row in rows],
    }
    out_base = ROOT / str(args.baseline_json)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    out_base.write_text(json.dumps(baseline, indent=2, sort_keys=True), encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "rows_total": len(rows),
                "output_json": str(out_json),
                "output_md": str(out_md),
                "baseline_json": str(out_base),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
