#!/usr/bin/env python3
"""Generate consolidated Q/H validation + plugin path report from latest eval artifact."""

from __future__ import annotations

import glob
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ADV_DIR = ROOT / "artifacts" / "advanced10"


def _latest_advanced20() -> Path:
    for pattern in ("advanced20_*_rerun1.json", "advanced20_*.json"):
        matches = sorted(ADV_DIR.glob(pattern))
        if matches:
            return matches[-1]
    raise FileNotFoundError("no advanced20 artifact found under artifacts/advanced10")


def _confidence_score(row: dict[str, Any]) -> float:
    """Deterministic confidence heuristic for validation reporting."""
    ev = row.get("expected_eval") if isinstance(row.get("expected_eval"), dict) else {}
    evaluated = bool(ev.get("evaluated", False))
    passed = ev.get("passed")
    answer_state = str(row.get("answer_state") or "").strip().lower()
    providers = row.get("providers") if isinstance(row.get("providers"), list) else []
    provider_count = len(providers)
    summary = str(row.get("summary") or "")

    if evaluated:
        if passed is True:
            score = 0.93 if answer_state == "ok" else 0.86
        else:
            score = 0.16 if answer_state == "no_evidence" else 0.24
    else:
        if answer_state == "ok":
            score = 0.58
            if provider_count > 0:
                score += 0.10
            if provider_count >= 2:
                score += 0.05
            if "Indeterminate:" in summary:
                score -= 0.18
        elif answer_state == "no_evidence":
            score = 0.18
        else:
            score = 0.30
    return max(0.01, min(0.99, round(score, 2)))


def _confidence_label(score: float) -> str:
    if score >= 0.80:
        return "high"
    if score >= 0.50:
        return "medium"
    return "low"


def main() -> int:
    artifact_path = _latest_advanced20()
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    report_rel = str(artifact.get("report") or "").strip()
    if not report_rel:
        raise ValueError("artifact missing report path")
    run_report_path = (ROOT / report_rel).resolve() if not Path(report_rel).is_absolute() else Path(report_rel)
    run_report = json.loads(run_report_path.read_text(encoding="utf-8"))

    rows = artifact.get("rows", []) if isinstance(artifact.get("rows"), list) else []
    for row in rows:
        score = _confidence_score(row)
        row["_confidence"] = score
        row["_confidence_label"] = _confidence_label(score)

    load_report = (
        ((run_report.get("plugins") or {}).get("load_report") or {})
        if isinstance(run_report.get("plugins"), dict)
        else {}
    )
    loaded = list(load_report.get("loaded") or [])
    failed = list(load_report.get("failed") or [])
    skipped = list(load_report.get("skipped") or [])

    all_plugins: list[str] = []
    seen: set[str] = set()
    for plugin_id in loaded + failed + skipped:
        if plugin_id in seen:
            continue
        seen.add(plugin_id)
        all_plugins.append(plugin_id)

    usage: dict[str, list[dict[str, Any]]] = {plugin_id: [] for plugin_id in all_plugins}
    for row in rows:
        qid = str(row.get("id") or "?")
        conf = float(row.get("_confidence") or 0.0)
        providers = row.get("providers") if isinstance(row.get("providers"), list) else []
        for provider in providers:
            if not isinstance(provider, dict):
                continue
            plugin_id = str(provider.get("provider_id") or "").strip()
            if not plugin_id:
                continue
            if plugin_id not in usage:
                usage[plugin_id] = []
                all_plugins.append(plugin_id)
            usage[plugin_id].append(
                {
                    "id": qid,
                    "confidence": conf,
                    "contribution_bp": provider.get("contribution_bp"),
                    "claim_count": provider.get("claim_count"),
                    "citation_count": provider.get("citation_count"),
                }
            )

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    output_path = ROOT / "docs" / "reports" / "question-validation-plugin-trace-2026-02-13.md"

    lines: list[str] = []
    lines.append("# Question Validation + Plugin Path Trace (Q/H)")
    lines.append("")
    lines.append(f"- Generated: `{now}`")
    lines.append(f"- Artifact: `{artifact_path.relative_to(ROOT)}`")
    lines.append(f"- Run report: `{run_report_path.relative_to(ROOT)}`")
    lines.append(
        f"- Evaluated summary: total={artifact.get('evaluated_total')} passed={artifact.get('evaluated_passed')} failed={artifact.get('evaluated_failed')}"
    )
    lines.append("")
    lines.append("## Confidence Rubric")
    lines.append("- `high` (>=0.80): strict-evaluated pass or strongly supported non-strict answer with multiple providers")
    lines.append("- `medium` (0.50-0.79): non-strict `ok` answer with some provider support")
    lines.append("- `low` (<0.50): strict-evaluated fail or `no_evidence` / indeterminate outputs")
    lines.append("- Note: `Q1..Q10` are non-strict in this artifact (`expected_eval.evaluated=false`), so confidence there is heuristic.")
    lines.append("")
    lines.append("## Question Results (All Q and H)")
    lines.append("| ID | Strict Evaluated | Strict Passed | Answer State | Confidence | Label | Winner | Providers In Path |")
    lines.append("| --- | ---: | ---: | --- | ---: | --- | --- | ---: |")
    for row in rows:
        ev = row.get("expected_eval") if isinstance(row.get("expected_eval"), dict) else {}
        lines.append(
            f"| {row.get('id')} | {ev.get('evaluated')} | {ev.get('passed')} | {row.get('answer_state')} | {float(row.get('_confidence')):.2f} | {row.get('_confidence_label')} | {row.get('winner')} | {len(row.get('providers') or [])} |"
        )
    lines.append("")
    lines.append("## Plugin Execution + Answer Path")
    lines.append("| Plugin ID | Load Status | In Any Answer Path | Answer Count | Answer IDs | Avg Confidence |")
    lines.append("| --- | --- | --- | ---: | --- | ---: |")
    for plugin_id in all_plugins:
        if plugin_id in loaded:
            status = "loaded"
        elif plugin_id in failed:
            status = "failed"
        elif plugin_id in skipped:
            status = "skipped"
        else:
            status = "seen_in_path_only"
        entries = usage.get(plugin_id, [])
        ids = ", ".join(item["id"] for item in entries) if entries else "-"
        avg_conf = f"{mean(item['confidence'] for item in entries):.2f}" if entries else "-"
        lines.append(f"| {plugin_id} | {status} | {bool(entries)} | {len(entries)} | {ids} | {avg_conf} |")
    lines.append("")
    lines.append("## Per-Question Plugin Path + Confidence")
    for row in rows:
        qid = str(row.get("id") or "?")
        question = str(row.get("question") or "").strip()
        ev = row.get("expected_eval") if isinstance(row.get("expected_eval"), dict) else {}
        lines.append(f"### {qid}")
        lines.append(f"- Question: {question}")
        lines.append(f"- Answer state: `{row.get('answer_state')}`")
        lines.append(f"- Strict evaluated: `{ev.get('evaluated')}` | strict passed: `{ev.get('passed')}`")
        lines.append(f"- Confidence: `{float(row.get('_confidence')):.2f}` ({row.get('_confidence_label')})")
        providers = row.get("providers") if isinstance(row.get("providers"), list) else []
        if not providers:
            lines.append("- Plugins in answer path: none")
        else:
            lines.append("- Plugins in answer path:")
            for provider in providers:
                if not isinstance(provider, dict):
                    continue
                lines.append(
                    f"  - `{provider.get('provider_id')}` | contribution_bp={provider.get('contribution_bp')} | claim_count={provider.get('claim_count')} | citation_count={provider.get('citation_count')}"
                )
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output_path), "artifact": str(artifact_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
