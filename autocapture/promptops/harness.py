"""Template-level evaluation harness for PromptOps."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from autocapture.promptops.engine import PromptOpsLayer


@dataclass(frozen=True)
class TemplateEvalCase:
    case_id: str
    prompt_id: str
    prompt: str
    sources: list[Any] = field(default_factory=list)
    strategy: str | None = None
    examples: list[dict[str, Any]] | None = None
    expected: dict[str, Any] = field(default_factory=dict)
    promptops_overrides: dict[str, Any] | None = None


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_text(text: str) -> str:
    return str(text).replace("\r\n", "\n").replace("\r", "\n")


def _hash_prompt(text: str) -> str:
    return _sha256_text(_normalize_text(text))


def _hash_sources(sources: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical_json_bytes(sources)).hexdigest()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _apply_eval_overrides(config: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    promptops_cfg = config.get("promptops", {}) if isinstance(config, dict) else {}
    base_overrides = {
        "enabled": True,
        "mode": "auto_apply",
        "persist_prompts": False,
        "history": {"enabled": False, "include_prompt": False},
        "github": {"enabled": False},
    }
    merged_promptops = _deep_merge(promptops_cfg, base_overrides)
    if isinstance(overrides, dict) and overrides:
        merged_promptops = _deep_merge(merged_promptops, overrides)
    merged = deepcopy(config)
    merged["promptops"] = merged_promptops
    return merged


def _parse_cases(cases: list[dict[str, Any]]) -> list[TemplateEvalCase]:
    seen: set[str] = set()
    parsed: list[TemplateEvalCase] = []
    for idx, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"case {idx} must be an object")
        case_id = str(case.get("id") or case.get("case_id") or "").strip()
        if not case_id:
            raise ValueError(f"case {idx} missing id")
        if case_id in seen:
            raise ValueError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        prompt_id = str(case.get("prompt_id") or "default").strip() or "default"
        prompt = str(case.get("prompt") or "")
        sources = case.get("sources", [])
        if sources is None:
            sources = []
        if not isinstance(sources, list):
            raise ValueError(f"case {case_id} sources must be a list")
        parsed.append(
            TemplateEvalCase(
                case_id=case_id,
                prompt_id=prompt_id,
                prompt=prompt,
                sources=list(sources),
                strategy=case.get("strategy"),
                examples=case.get("examples") if isinstance(case.get("examples"), list) else None,
                expected=dict(case.get("expected") or {}),
                promptops_overrides=case.get("promptops_overrides") if isinstance(case.get("promptops_overrides"), dict) else None,
            )
        )
    return parsed


def load_eval_cases(path: str | Path) -> list[TemplateEvalCase]:
    raw = Path(path).read_text(encoding="utf-8")
    payload = json.loads(raw)
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError("promptops eval cases must be a list or {cases: [...]} object")
    return _parse_cases(cases)


def _check_required_tokens(prompt: str, tokens: Iterable[str]) -> bool:
    text = prompt.lower()
    for token in tokens:
        if str(token).lower() not in text:
            return False
    return True


def run_template_eval(
    config: dict[str, Any],
    cases: Iterable[TemplateEvalCase | dict[str, Any]],
    *,
    include_prompt: bool = False,
    include_sources: bool = False,
    promptops_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    eval_cfg = config.get("promptops", {}).get("eval", {}) if isinstance(config, dict) else {}
    config_overrides = None
    if isinstance(eval_cfg, dict):
        config_overrides = eval_cfg.get("overrides") if isinstance(eval_cfg.get("overrides"), dict) else None
    merged_overrides = None
    if promptops_overrides or config_overrides:
        merged_overrides = _deep_merge(promptops_overrides or {}, config_overrides or {})
    base_config = _apply_eval_overrides(config, merged_overrides)

    parsed: list[TemplateEvalCase] = []
    for entry in cases:
        if isinstance(entry, TemplateEvalCase):
            parsed.append(entry)
        elif isinstance(entry, dict):
            parsed.extend(load_eval_cases_from_dict(entry))
        else:
            raise ValueError("eval cases must be TemplateEvalCase or dict")

    results: list[dict[str, Any]] = []
    total = 0
    failed = 0
    for case in sorted(parsed, key=lambda c: c.case_id):
        total += 1
        case_config = base_config
        if case.promptops_overrides:
            case_config = _apply_eval_overrides(base_config, case.promptops_overrides)
        case_promptops_cfg = case_config.get("promptops", {}) if isinstance(case_config, dict) else {}
        case_promptops_hash = _sha256_bytes(_canonical_json_bytes(case_promptops_cfg))
        layer = PromptOpsLayer(case_config)
        try:
            result = layer.prepare_prompt(
                case.prompt,
                prompt_id=case.prompt_id,
                sources=case.sources,
                examples=case.examples,
                persist=False,
                strategy=case.strategy,
                # Eval harness must use the case prompt as the source of truth;
                # stored prompt templates would make results nondeterministic.
                prefer_stored_prompt=False,
            )
            prompt_hash = _hash_prompt(result.prompt)
            sources_hash = _hash_sources(result.sources)
            validation_ok = bool(result.validation.get("ok")) if isinstance(result.validation, dict) else False
            evaluation_ok = bool(result.evaluation.get("ok")) if isinstance(result.evaluation, dict) else False
            evaluation_pass_rate = result.evaluation.get("pass_rate") if isinstance(result.evaluation, dict) else None
            evaluation_citation = result.evaluation.get("citation_coverage") if isinstance(result.evaluation, dict) else None

            checks: list[dict[str, Any]] = []
            expected = case.expected or {}
            expected_prompt = expected.get("prompt")
            if expected_prompt is not None:
                ok = result.prompt == expected_prompt
                checks.append({"check": "prompt_match", "ok": ok, "expected": expected_prompt, "actual": result.prompt})
            expected_hash = expected.get("prompt_sha256") or expected.get("prompt_hash")
            if expected_hash is not None:
                ok = str(prompt_hash) == str(expected_hash)
                checks.append({"check": "prompt_sha256", "ok": ok, "expected": expected_hash, "actual": prompt_hash})
            expected_sources = expected.get("sources_sha256") or expected.get("sources_hash")
            if expected_sources is not None:
                ok = str(sources_hash) == str(expected_sources)
                checks.append({"check": "sources_sha256", "ok": ok, "expected": expected_sources, "actual": sources_hash})
            required_tokens = expected.get("required_tokens") or expected.get("tokens")
            if required_tokens:
                ok = _check_required_tokens(result.prompt, required_tokens)
                checks.append({"check": "required_tokens", "ok": ok, "expected": list(required_tokens)})
            expected_applied = expected.get("applied")
            if expected_applied is not None:
                ok = bool(result.applied) == bool(expected_applied)
                checks.append({"check": "applied", "ok": ok, "expected": bool(expected_applied), "actual": bool(result.applied)})
            expected_validation = expected.get("validation_ok")
            if expected_validation is not None:
                ok = validation_ok == bool(expected_validation)
                checks.append({"check": "validation_ok", "ok": ok, "expected": bool(expected_validation), "actual": validation_ok})
            expected_eval = expected.get("evaluation_ok")
            if expected_eval is not None:
                ok = evaluation_ok == bool(expected_eval)
                checks.append({"check": "evaluation_ok", "ok": ok, "expected": bool(expected_eval), "actual": evaluation_ok})
            min_pass_rate = expected.get("min_pass_rate")
            if min_pass_rate is not None and evaluation_pass_rate is not None:
                ok = float(evaluation_pass_rate) >= float(min_pass_rate)
                checks.append({"check": "min_pass_rate", "ok": ok, "expected": float(min_pass_rate), "actual": evaluation_pass_rate})
            min_citation = expected.get("min_citation_coverage")
            if min_citation is not None and evaluation_citation is not None:
                ok = float(evaluation_citation) >= float(min_citation)
                checks.append({"check": "min_citation_coverage", "ok": ok, "expected": float(min_citation), "actual": evaluation_citation})

            ok = all(check.get("ok") for check in checks) if checks else evaluation_ok and validation_ok
            if not ok:
                failed += 1
            case_payload = {
                "case_id": case.case_id,
                "prompt_id": case.prompt_id,
                "ok": ok,
                "applied": bool(result.applied),
                "mode": result.mode,
                "strategy": str((result.trace or {}).get("strategy") or (case.strategy or "none")),
                "promptops_config_sha256": case_promptops_hash,
                "prompt_sha256": prompt_hash,
                "sources_sha256": sources_hash,
                "source_count": int(len(result.sources)),
                "promptops_trace": result.trace if isinstance(result.trace, dict) else None,
                "validation": result.validation,
                "evaluation": result.evaluation,
                "checks": checks,
            }
            if include_prompt:
                case_payload["prompt"] = result.prompt
            if include_sources:
                case_payload["sources"] = result.sources
            results.append(case_payload)
        except Exception as exc:
            failed += 1
            results.append(
                {
                    "case_id": case.case_id,
                    "prompt_id": case.prompt_id,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "checks": [],
                }
            )

    promptops_cfg = base_config.get("promptops", {}) if isinstance(base_config, dict) else {}
    promptops_hash = _sha256_bytes(_canonical_json_bytes(promptops_cfg))
    report = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "promptops_config_sha256": promptops_hash,
        "summary": {
            "total": total,
            "passed": total - failed,
            "failed": failed,
        },
        "cases": results,
    }
    return report


def load_eval_cases_from_dict(payload: dict[str, Any]) -> list[TemplateEvalCase]:
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if cases is None:
        cases = [payload]
    if not isinstance(cases, list):
        raise ValueError("promptops eval case must be a dict or list")
    return _parse_cases(cases)
