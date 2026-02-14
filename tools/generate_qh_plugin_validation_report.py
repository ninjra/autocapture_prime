#!/usr/bin/env python3
"""Generate consolidated Q/H validation + plugin path report from latest eval artifact."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ADV_DIR = ROOT / "artifacts" / "advanced10"


def _latest_advanced20() -> Path:
    candidates = sorted(ADV_DIR.glob("advanced*.json"))
    best: Path | None = None
    best_mtime = -1.0
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            continue
        if len(rows) < 20:
            continue
        try:
            mt = path.stat().st_mtime
        except Exception:
            mt = 0.0
        if mt > best_mtime:
            best = path
            best_mtime = mt
    if best is not None:
        return best
    for pattern in ("advanced20_*_rerun1.json", "advanced20_*.json"):
        matches = sorted(ADV_DIR.glob(pattern))
        if matches:
            return matches[-1]
    raise FileNotFoundError("no advanced20 artifact found under artifacts/advanced10")


def _confidence_score(row: dict[str, Any]) -> float:
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
            if "indeterminate:" in summary.casefold():
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


def _plugin_status_map(run_report: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    plugins = run_report.get("plugins", {}) if isinstance(run_report.get("plugins"), dict) else {}
    load_report = plugins.get("load_report", {}) if isinstance(plugins.get("load_report"), dict) else {}
    loaded = [str(x).strip() for x in (load_report.get("loaded") or []) if str(x).strip()]
    failed = [str(x).strip() for x in (load_report.get("failed") or []) if str(x).strip()]
    skipped = [str(x).strip() for x in (load_report.get("skipped") or []) if str(x).strip()]
    all_plugins: list[str] = []
    seen: set[str] = set()
    for plugin_id in loaded + failed + skipped:
        if plugin_id in seen:
            continue
        seen.add(plugin_id)
        all_plugins.append(plugin_id)
    status: dict[str, str] = {}
    for plugin_id in all_plugins:
        if plugin_id in loaded:
            status[plugin_id] = "loaded"
        elif plugin_id in failed:
            status[plugin_id] = "failed"
        elif plugin_id in skipped:
            status[plugin_id] = "skipped"
        else:
            status[plugin_id] = "unknown"
    return all_plugins, status


def _plugin_decision(*, status: str, in_path: int, strict_pass: int, strict_fail: int, conf_delta: float) -> str:
    if status == "failed":
        return "fix_required"
    if in_path <= 0 and status == "loaded":
        return "remove_or_rewire"
    if strict_fail > strict_pass:
        return "tune"
    if strict_pass > 0 and conf_delta > 0.02:
        return "keep"
    return "neutral"


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
    overall_conf = mean(float(row.get("_confidence") or 0.0) for row in rows) if rows else 0.0

    all_plugins, status_map = _plugin_status_map(run_report)
    usage: dict[str, list[dict[str, Any]]] = {plugin_id: [] for plugin_id in all_plugins}

    for row in rows:
        qid = str(row.get("id") or "?")
        conf = float(row.get("_confidence") or 0.0)
        ev = row.get("expected_eval") if isinstance(row.get("expected_eval"), dict) else {}
        stage_ms = row.get("stage_ms") if isinstance(row.get("stage_ms"), dict) else {}
        total_ms = float(stage_ms.get("total", 0.0) or 0.0)
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
                status_map.setdefault(plugin_id, "seen_in_path_only")
            usage[plugin_id].append(
                {
                    "id": qid,
                    "confidence": conf,
                    "contribution_bp": int(provider.get("contribution_bp", 0) or 0),
                    "claim_count": int(provider.get("claim_count", 0) or 0),
                    "citation_count": int(provider.get("citation_count", 0) or 0),
                    "evaluated": bool(ev.get("evaluated", False)),
                    "passed": bool(ev.get("passed", False)),
                    "stage_total_ms": total_ms,
                    "est_latency_ms": float(provider.get("estimated_latency_ms", 0.0) or 0.0),
                }
            )

    plugin_rows: list[dict[str, Any]] = []
    total_questions = int(len(rows))
    for plugin_id in all_plugins:
        entries = usage.get(plugin_id, [])
        in_path = int(len(entries))
        out_of_path = max(0, total_questions - in_path)
        strict_entries = [item for item in entries if bool(item.get("evaluated", False))]
        strict_pass = int(sum(1 for item in strict_entries if bool(item.get("passed", False))))
        strict_fail = int(sum(1 for item in strict_entries if not bool(item.get("passed", False))))
        strict_neutral = int(max(0, len(entries) - len(strict_entries)))
        avg_conf = float(mean(float(item["confidence"]) for item in entries)) if entries else 0.0
        conf_delta = float(round(avg_conf - overall_conf, 4))
        mean_latency = float(mean(float(item.get("est_latency_ms", 0.0)) for item in entries)) if entries else 0.0
        decision = _plugin_decision(
            status=status_map.get(plugin_id, "unknown"),
            in_path=in_path,
            strict_pass=strict_pass,
            strict_fail=strict_fail,
            conf_delta=conf_delta,
        )
        plugin_rows.append(
            {
                "plugin_id": plugin_id,
                "status": status_map.get(plugin_id, "unknown"),
                "in_path_count": in_path,
                "out_of_path_count": out_of_path,
                "strict_pass_count": strict_pass,
                "strict_fail_count": strict_fail,
                "strict_neutral_count": strict_neutral,
                "avg_confidence": round(avg_conf, 4),
                "confidence_delta": conf_delta,
                "mean_est_latency_ms": round(mean_latency, 3),
                "decision": decision,
                "answer_ids": ", ".join(item.get("id", "?") for item in entries) if entries else "-",
            }
        )
    plugin_rows.sort(key=lambda item: (str(item["status"]), -int(item["in_path_count"]), str(item["plugin_id"])))

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    output_path = ROOT / "docs" / "reports" / "question-validation-plugin-trace-2026-02-13.md"
    json_output = ROOT / "artifacts" / "advanced10" / "question_validation_plugin_trace_latest.json"

    lines: list[str] = []
    lines.append("# Question Validation + Plugin Path Trace (Q/H)")
    lines.append("")
    lines.append(f"- Generated: `{now}`")
    lines.append(f"- Artifact: `{artifact_path.relative_to(ROOT)}`")
    lines.append(f"- Run report: `{run_report_path.relative_to(ROOT)}`")
    lines.append(
        f"- Evaluated summary: total={artifact.get('evaluated_total')} passed={artifact.get('evaluated_passed')} failed={artifact.get('evaluated_failed')}"
    )
    lines.append(f"- Overall confidence mean: `{overall_conf:.4f}`")
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
    lines.append("## Plugin Inventory + Effectiveness")
    lines.append("| Plugin ID | Status | In Path | Out Path | Strict Pass | Strict Fail | Neutral | Avg Conf | Conf Δ | Mean Est Latency ms | Decision |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for item in plugin_rows:
        lines.append(
            f"| {item['plugin_id']} | {item['status']} | {item['in_path_count']} | {item['out_of_path_count']} | {item['strict_pass_count']} | {item['strict_fail_count']} | {item['strict_neutral_count']} | {item['avg_confidence']:.4f} | {item['confidence_delta']:+.4f} | {item['mean_est_latency_ms']:.3f} | {item['decision']} |"
        )

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
                    f"  - `{provider.get('provider_id')}` | contribution_bp={provider.get('contribution_bp')} | claim_count={provider.get('claim_count')} | citation_count={provider.get('citation_count')} | est_latency_ms={provider.get('estimated_latency_ms', 0)}"
                )
        lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(
            {
                "ok": True,
                "generated_utc": now,
                "artifact": str(artifact_path),
                "run_report": str(run_report_path),
                "overall_confidence": round(overall_conf, 6),
                "rows": rows,
                "plugin_rows": plugin_rows,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "output": str(output_path), "json": str(json_output), "artifact": str(artifact_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
