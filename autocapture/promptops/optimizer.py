"""Idle-safe PromptOps optimizer worker.

This worker mines PromptOps interaction metrics, identifies weak prompt IDs,
and proposes safer prompt variants for review/autopromotion under strict gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from autocapture.promptops.evaluate import evaluate_prompt
from autocapture.promptops.examples import build_examples_from_traces, load_examples_file, write_examples_file
from autocapture.promptops.propose import propose_prompt
from autocapture.promptops.service import get_promptops_layer
from autocapture.promptops.validate import DEFAULT_BANNED, validate_prompt


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return float(round(ordered[0], 3))
    p = max(0.0, min(100.0, float(pct)))
    pos = (len(ordered) - 1) * (p / 100.0)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    w = pos - lo
    val = ordered[lo] * (1.0 - w) + ordered[hi] * w
    return float(round(val, 3))


def _safe_float(value: Any) -> float:
    try:
        out = float(value or 0.0)
    except Exception:
        return 0.0
    if out < 0.0:
        return 0.0
    return float(round(out, 6))


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().casefold()
    return text in {"1", "true", "yes", "on"}


def _load_jsonl(path: Path, *, max_rows: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    for line in lines[-max(1, int(max_rows)) :]:
        raw = str(line or "").strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


@dataclass(frozen=True)
class PromptWeakness:
    prompt_id: str
    total: int
    success_rate: float
    latency_p95_ms: float
    failure_count: int
    reasons: list[str]


class PromptOpsOptimizer:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config if isinstance(config, dict) else {}
        self._last_run_monotonic: float | None = None
        self._layer = get_promptops_layer(self._config)

    def _promptops_cfg(self) -> dict[str, Any]:
        cfg = self._config.get("promptops", {})
        return cfg if isinstance(cfg, dict) else {}

    def _optimizer_cfg(self) -> dict[str, Any]:
        promptops = self._promptops_cfg()
        cfg = promptops.get("optimizer", {})
        return cfg if isinstance(cfg, dict) else {}

    def _data_root(self) -> Path:
        paths = self._config.get("paths", {}) if isinstance(self._config, dict) else {}
        storage = self._config.get("storage", {}) if isinstance(self._config, dict) else {}
        data_dir = paths.get("data_dir") or storage.get("data_dir") or "data"
        return Path(str(data_dir))

    def _metrics_path(self) -> Path:
        promptops = self._promptops_cfg()
        metrics = promptops.get("metrics", {}) if isinstance(promptops, dict) else {}
        out = str(metrics.get("output_path") or "").strip()
        if out:
            return Path(out)
        return self._data_root() / "promptops" / "metrics.jsonl"

    def _trace_path(self) -> Path:
        cfg = self._optimizer_cfg()
        raw = str(cfg.get("query_trace_path") or "").strip()
        if raw:
            return Path(raw)
        return self._data_root() / "facts" / "query_trace.ndjson"

    def _examples_path(self) -> Path:
        promptops = self._promptops_cfg()
        raw = str(promptops.get("examples_path") or "").strip()
        if raw:
            return Path(raw)
        return self._data_root() / "promptops" / "examples.json"

    def _report_path(self) -> Path:
        cfg = self._optimizer_cfg()
        out = str(cfg.get("output_path") or "").strip()
        if out:
            return Path(out)
        return Path("artifacts/promptops/optimizer_latest.json")

    def _enabled(self) -> bool:
        return bool(self._optimizer_cfg().get("enabled", False))

    def _interval_s(self) -> float:
        cfg = self._optimizer_cfg()
        try:
            value = float(cfg.get("interval_s", 300))
        except Exception:
            value = 300.0
        return max(1.0, value)

    def due(self, *, now_monotonic: float | None = None) -> bool:
        if not self._enabled():
            return False
        now = time.monotonic() if now_monotonic is None else float(now_monotonic)
        if self._last_run_monotonic is None:
            return True
        return (now - self._last_run_monotonic) >= self._interval_s()

    def _examples_for(self, prompt_id: str) -> list[dict[str, Any]]:
        promptops = self._promptops_cfg()
        examples = promptops.get("examples", {})
        if isinstance(examples, dict):
            rows = examples.get(prompt_id, [])
            if isinstance(rows, list) and rows:
                return list(rows)
            aliases = []
            if str(prompt_id) == "query":
                aliases.append("query.default")
            elif str(prompt_id) == "query.default":
                aliases.append("query")
            for alias in aliases:
                alias_rows = examples.get(alias, [])
                if isinstance(alias_rows, list) and alias_rows:
                    return list(alias_rows)
        if isinstance(examples, list):
            return list(examples)
        try:
            rows = load_examples_file(self._examples_path(), prompt_id=str(prompt_id))
            if rows:
                return rows
        except Exception:
            return []
        return []

    def _bootstrap_prompt_from_metrics(self, rows: list[dict[str, Any]], prompt_id: str) -> str:
        for row in reversed(rows):
            if str(row.get("type") or "") != "promptops.model_interaction":
                continue
            if str(row.get("prompt_id") or "").strip() != str(prompt_id):
                continue
            effective = str(row.get("prompt_effective_text") or "").strip()
            if effective:
                return effective
            raw_input = str(row.get("prompt_input_text") or "").strip()
            if raw_input:
                return raw_input
        return ""

    @staticmethod
    def _fallback_prompt(prompt_id: str) -> str:
        pid = str(prompt_id or "").strip()
        if pid.startswith("hard_vlm."):
            return "Answer with policy-grounded reasoning and cite the strongest evidence."
        if pid in {"query", "query.default"}:
            return "Rewrite the query to be clear, concise, and answerable from local evidence."
        if pid in {"state_query", "state.query"}:
            return "Answer using extracted state records and include citations when available."
        return ""

    def _find_weak_prompt_ids(self, rows: list[dict[str, Any]]) -> list[PromptWeakness]:
        cfg = self._optimizer_cfg()
        min_interactions = max(1, int(cfg.get("min_interactions", 10) or 10))
        min_success_rate = float(cfg.get("min_success_rate", 0.70) or 0.70)
        max_latency_p95 = float(cfg.get("max_latency_p95_ms", 4000.0) or 4000.0)
        by_prompt: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if str(row.get("type") or "") != "promptops.model_interaction":
                continue
            prompt_id = str(row.get("prompt_id") or "").strip()
            if not prompt_id:
                continue
            by_prompt.setdefault(prompt_id, []).append(row)

        weak: list[PromptWeakness] = []
        for prompt_id, bucket in by_prompt.items():
            total = int(len(bucket))
            if total < min_interactions:
                continue
            successes = int(sum(1 for row in bucket if _safe_bool(row.get("success"))))
            fails = int(max(0, total - successes))
            success_rate = float(round((successes / total), 6)) if total else 0.0
            latencies = [_safe_float(row.get("latency_ms")) for row in bucket]
            latency_p95 = _percentile(latencies, 95.0)
            reasons: list[str] = []
            if success_rate < min_success_rate:
                reasons.append("low_success_rate")
            if latency_p95 > max_latency_p95:
                reasons.append("high_latency_p95")
            if reasons:
                weak.append(
                    PromptWeakness(
                        prompt_id=prompt_id,
                        total=total,
                        success_rate=success_rate,
                        latency_p95_ms=latency_p95,
                        failure_count=fails,
                        reasons=reasons,
                    )
                )
        weak.sort(key=lambda item: (len(item.reasons), item.failure_count, item.latency_p95_ms), reverse=True)
        limit = max(1, int(cfg.get("max_prompt_ids", 3) or 3))
        return weak[:limit]

    def run_once(
        self,
        *,
        user_active: bool,
        idle_seconds: float | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        now = time.monotonic()
        cfg = self._optimizer_cfg()
        result: dict[str, Any] = {
            "schema_version": 1,
            "ts_utc": _utc_now(),
            "ok": True,
            "enabled": self._enabled(),
            "user_active": bool(user_active),
            "idle_seconds": float(idle_seconds or 0.0),
            "force": bool(force),
            "skipped": False,
            "skip_reason": "",
            "weak_prompt_ids": [],
            "candidates": [],
            "applied_count": 0,
            "metrics_rows": 0,
            "metrics_path": str(self._metrics_path()),
            "examples_refreshed": False,
            "examples_path": str(self._examples_path()),
        }
        if not self._enabled():
            result["skipped"] = True
            result["skip_reason"] = "disabled"
            return self._persist_report(result)
        if bool(user_active) and not bool(force):
            result["skipped"] = True
            result["skip_reason"] = "user_active"
            return self._persist_report(result)
        if not bool(force) and not self.due(now_monotonic=now):
            result["skipped"] = True
            result["skip_reason"] = "interval_not_due"
            return self._persist_report(result)

        max_rows = max(100, int(cfg.get("metrics_window_rows", 5000) or 5000))
        rows = _load_jsonl(self._metrics_path(), max_rows=max_rows)
        result["metrics_rows"] = int(len(rows))
        if bool(cfg.get("refresh_examples", True)):
            try:
                built = build_examples_from_traces(
                    query_trace_path=self._trace_path(),
                    metrics_path=self._metrics_path(),
                    max_trace_rows=max_rows,
                )
                write_examples_file(
                    self._examples_path(),
                    examples=built.examples,
                    source_counts=built.source_counts,
                )
                result["examples_refreshed"] = True
                result["example_prompt_ids"] = sorted(list((built.examples or {}).keys()))
            except Exception as exc:
                result["examples_refreshed"] = False
                result["examples_error"] = f"{type(exc).__name__}: {exc}"
        weak = self._find_weak_prompt_ids(rows)
        result["weak_prompt_ids"] = [
            {
                "prompt_id": item.prompt_id,
                "total": item.total,
                "success_rate": item.success_rate,
                "latency_p95_ms": item.latency_p95_ms,
                "failure_count": item.failure_count,
                "reasons": item.reasons,
            }
            for item in weak
        ]

        strategies = cfg.get("strategies", ["normalize_query", "model_contract"])
        if not isinstance(strategies, list) or not strategies:
            strategies = ["normalize_query", "model_contract"]
        auto_promote = bool(cfg.get("auto_promote", False))
        min_delta = float(cfg.get("min_pass_rate_delta", 0.05) or 0.05)
        promptops = self._promptops_cfg()
        require_citations = bool(promptops.get("require_citations", True))
        for item in weak:
            current_prompt = self._layer._store.get(item.prompt_id)  # noqa: SLF001
            bootstrapped_from_metrics = False
            if not current_prompt:
                current_prompt = self._bootstrap_prompt_from_metrics(rows, item.prompt_id)
                bootstrapped_from_metrics = bool(current_prompt)
            if not current_prompt:
                current_prompt = self._fallback_prompt(item.prompt_id)
            if not current_prompt:
                result["candidates"].append(
                    {
                        "prompt_id": item.prompt_id,
                        "status": "skipped",
                        "reason": "prompt_not_found",
                    }
                )
                continue
            examples = self._examples_for(item.prompt_id)
            baseline = evaluate_prompt(
                current_prompt,
                examples,
                min_pass_rate=float(max(0.0, min(1.0, float(int(promptops.get("min_pass_rate_pct", 100)) / 100.0)))),
                require_citations=require_citations,
            )
            baseline_rate = float(baseline.get("pass_rate", 0.0) or 0.0)
            best: dict[str, Any] | None = None
            for strategy in strategies:
                proposal = propose_prompt(current_prompt, {"sources": []}, strategy=str(strategy))
                candidate = str(proposal.get("proposal") or "")
                if candidate == current_prompt:
                    continue
                validation = validate_prompt(
                    candidate,
                    max_chars=int(promptops.get("max_chars", 8000)),
                    max_tokens=int(promptops.get("max_tokens", 2000)),
                    banned_patterns=promptops.get("banned_patterns", DEFAULT_BANNED),
                )
                evaluation = evaluate_prompt(
                    candidate,
                    examples,
                    min_pass_rate=float(max(0.0, min(1.0, float(int(promptops.get("min_pass_rate_pct", 100)) / 100.0)))),
                    require_citations=require_citations,
                )
                pass_rate = float(evaluation.get("pass_rate", 0.0) or 0.0)
                delta = float(round(pass_rate - baseline_rate, 6))
                row = {
                    "strategy": str(strategy),
                    "validation_ok": bool(validation.get("ok", False)),
                    "evaluation_ok": bool(evaluation.get("ok", False)),
                    "evaluation_total": int(evaluation.get("total", 0) or 0),
                    "pass_rate": pass_rate,
                    "pass_rate_delta": delta,
                    "candidate": candidate,
                }
                if best is None or (row["pass_rate_delta"], row["pass_rate"]) > (best["pass_rate_delta"], best["pass_rate"]):
                    best = row
            if best is None:
                result["candidates"].append(
                    {
                        "prompt_id": item.prompt_id,
                        "status": "skipped",
                        "reason": "no_candidate",
                    }
                )
                continue

            applied = False
            apply_reason = "not_applied"
            status = "ok"
            evaluation_total = int(best.get("evaluation_total", 0) or 0)
            if evaluation_total <= 0:
                status = "insufficient_examples"
                apply_reason = "insufficient_examples"
            can_apply = (
                bool(best.get("validation_ok", False))
                and bool(best.get("evaluation_ok", False))
                and evaluation_total > 0
                and float(best.get("pass_rate_delta", 0.0) or 0.0) >= min_delta
            )
            if auto_promote and can_apply:
                prep = self._layer.prepare_prompt(
                    current_prompt,
                    prompt_id=item.prompt_id,
                    strategy=str(best.get("strategy") or "none"),
                    sources=[],
                    examples=examples,
                    persist=True,
                    prefer_stored_prompt=True,
                )
                applied = bool(prep.applied)
                apply_reason = "applied" if applied else "prepare_not_applied"
            elif auto_promote and not can_apply:
                apply_reason = "candidate_below_gate"

            if applied:
                result["applied_count"] = int(result.get("applied_count", 0) or 0) + 1
            result["candidates"].append(
                {
                    "prompt_id": item.prompt_id,
                    "status": status,
                    "best_strategy": str(best.get("strategy") or ""),
                    "pass_rate": float(best.get("pass_rate", 0.0) or 0.0),
                    "pass_rate_delta": float(best.get("pass_rate_delta", 0.0) or 0.0),
                    "evaluation_total": evaluation_total,
                    "bootstrapped_prompt": bool(bootstrapped_from_metrics),
                    "applied": bool(applied),
                    "apply_reason": str(apply_reason),
                }
            )

        self._last_run_monotonic = now
        return self._persist_report(result)

    def _persist_report(self, report: dict[str, Any]) -> dict[str, Any]:
        path = self._report_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        report["report_path"] = str(path)
        return report
