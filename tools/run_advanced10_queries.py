#!/usr/bin/env python3
"""Run advanced question set against latest single-image run and persist results."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.inference.vllm_endpoint import check_external_vllm_ready, enforce_external_vllm_base_url

STRICT_DISALLOWED_ANSWER_PROVIDERS = frozenset(
    {
        "builtin.answer.synth_vllm_localhost",
        "hard_vlm.direct",
    }
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    try:
        return int(raw) if raw else int(default)
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    try:
        return float(raw) if raw else float(default)
    except Exception:
        return float(default)


def _emit_progress(stage: str, **fields: Any) -> None:
    payload: dict[str, Any] = {
        "event": "run_advanced10_queries.progress",
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "stage": str(stage),
    }
    payload.update(fields)
    try:
        print(json.dumps(payload, sort_keys=True), flush=True)
    except Exception:
        pass


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _latest_report(root: Path) -> Path:
    base = root / "artifacts" / "single_image_runs"
    latest = Path("")
    latest_mtime = -1.0
    if not base.exists():
        return latest
    for path in base.glob("*/report.json"):
        try:
            mt = path.stat().st_mtime
        except Exception:
            continue
        if mt > latest_mtime:
            latest_mtime = mt
            latest = path
    return latest


def _run_query_once(
    root: Path,
    *,
    cfg: str,
    data: str,
    query: str,
    image_path: str = "",
    timeout_s: float = 90.0,
    determinism: dict[str, str] | None = None,
    metadata_only: bool = False,
) -> dict[str, Any]:
    py = root / ".venv" / "bin" / "python"
    env = dict(os.environ)
    env["AUTOCAPTURE_CONFIG_DIR"] = str(cfg)
    env["AUTOCAPTURE_DATA_DIR"] = str(data)
    if str(image_path or "").strip():
        env["AUTOCAPTURE_QUERY_IMAGE_PATH"] = str(image_path).strip()
    env["AUTOCAPTURE_HARD_VLM_DEBUG"] = "1"
    if bool(metadata_only):
        env["AUTOCAPTURE_QUERY_METADATA_ONLY"] = "1"
        # Option A contract: no query-time hard VLM/image dependency in metadata mode.
        env["AUTOCAPTURE_ADV_HARD_VLM_MODE"] = "off"
        env["AUTOCAPTURE_QUERY_METADATA_ONLY_ALLOW_HARD_VLM"] = "0"
        env.pop("AUTOCAPTURE_QUERY_IMAGE_PATH", None)
        # Keep metadata-only strict runs bounded; defaults remain overrideable.
        env.setdefault("AUTOCAPTURE_HARD_VLM_MAX_CANDIDATES", "1")
        env.setdefault("AUTOCAPTURE_HARD_VLM_MAX_TOKENS", "256")
        env.setdefault("AUTOCAPTURE_HARD_VLM_TIMEOUT_S", "12")
        env.setdefault("AUTOCAPTURE_HARD_VLM_BUDGET_S", "20")
        env.setdefault("AUTOCAPTURE_HARD_VLM_RETRIES", "2")
    base_url_raw = str(env.get("AUTOCAPTURE_VLM_BASE_URL") or "").strip() or "http://127.0.0.1:8000/v1"
    try:
        env["AUTOCAPTURE_VLM_BASE_URL"] = enforce_external_vllm_base_url(base_url_raw)
    except Exception:
        env["AUTOCAPTURE_VLM_BASE_URL"] = "http://127.0.0.1:8000/v1"
    if not str(env.get("AUTOCAPTURE_VLM_API_KEY") or "").strip():
        api_key = _configured_vlm_api_key(Path(cfg))
        if api_key:
            env["AUTOCAPTURE_VLM_API_KEY"] = api_key
    det = determinism if isinstance(determinism, dict) else {}
    env["TZ"] = str(det.get("timezone") or "UTC")
    env["LANG"] = str(det.get("lang") or "C.UTF-8")
    env["LC_ALL"] = str(det.get("lang") or "C.UTF-8")
    env["PYTHONHASHSEED"] = str(det.get("pythonhashseed") or "0")
    env["AUTOCAPTURE_GOLDEN_STRICT"] = "1"
    if not str(env.get("AUTOCAPTURE_VLM_MODEL") or "").strip():
        model = _configured_vlm_model(Path(cfg))
        if model:
            env["AUTOCAPTURE_VLM_MODEL"] = model
    existing = str(env.get("PYTHONPATH") or "").strip()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{existing}" if existing else str(root)
    try:
        proc = subprocess.run(
            [str(py), "-m", "autocapture_nx", "query", str(query)],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(1.0, float(timeout_s)),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "error": f"query_timeout:{timeout_s}s",
            "answer": {},
            "processing": {},
            "stderr": str(getattr(exc, "stderr", "") or "").strip(),
            "stdout": str(getattr(exc, "stdout", "") or "").strip(),
        }
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": proc.stderr.strip() or proc.stdout.strip(),
            "answer": {},
            "processing": {},
            "stderr": proc.stderr.strip(),
            "stdout": proc.stdout.strip(),
        }
    try:
        out = json.loads(proc.stdout or "{}")
    except Exception as exc:
        return {"ok": False, "error": f"query_output_not_json:{type(exc).__name__}:{exc}", "answer": {}, "processing": {}}
    if not isinstance(out, dict):
        return {"ok": False, "error": "query_output_invalid", "answer": {}, "processing": {}}
    out["ok"] = True
    return out


def _is_instance_lock_error(result: dict[str, Any]) -> bool:
    text = str(result.get("error") or "").casefold()
    if "instance_lock_held" in text:
        return True
    text = f"{text}\n{str(result.get('stderr') or '').casefold()}\n{str(result.get('stdout') or '').casefold()}"
    return "instance_lock_held" in text


def _run_query(
    root: Path,
    *,
    cfg: str,
    data: str,
    query: str,
    image_path: str = "",
    timeout_s: float = 90.0,
    lock_retries: int = 4,
    lock_retry_wait_s: float = 0.25,
    determinism: dict[str, str] | None = None,
    metadata_only: bool = False,
) -> dict[str, Any]:
    retries = max(0, int(lock_retries))
    wait_s = max(0.0, float(lock_retry_wait_s))
    attempts = retries + 1
    last: dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        result = _run_query_once(
            root,
            cfg=cfg,
            data=data,
            query=query,
            image_path=image_path,
            timeout_s=timeout_s,
            determinism=determinism,
            metadata_only=metadata_only,
        )
        result["attempt"] = attempt
        result["attempts"] = attempts
        if bool(result.get("ok", False)):
            return result
        if not _is_instance_lock_error(result):
            return result
        last = result
        if attempt < attempts and wait_s > 0.0:
            time.sleep(wait_s * attempt)
    return last or {"ok": False, "error": "query_failed", "answer": {}, "processing": {}, "attempts": attempts}


def _contractize_query_failure(result: dict[str, Any], *, query: str, case_id: str) -> dict[str, Any]:
    """Return a deterministic no-evidence contract for query transport/runtime failures.

    Generic20 cases are best-effort and must still emit stable contract fields so
    matrix checks can distinguish "no evidence" from schema drift.
    """

    raw_error = str(result.get("error") or "").strip()
    reason = "query_failed"
    if "timeout" in raw_error.casefold():
        reason = "query_timeout"
    digest = hashlib.sha256(f"{case_id}|{query}".encode("utf-8")).hexdigest()[:16]
    query_run_id = f"qry_degraded_{digest}"
    summary = f"Not available yet ({reason})."
    bullets = [
        "Query contract degraded: upstream query execution failed.",
        f"reason: {reason}",
    ]
    return {
        "ok": True,
        "error": raw_error,
        "answer": {
            "state": "no_evidence",
            "summary": summary,
            "display": {
                "summary": summary,
                "bullets": bullets,
                "confidence_pct": 0.0,
            },
            "claims": [],
        },
        "processing": {
            "extraction": {
                "blocked": True,
                "blocked_reason": reason,
                "scheduled_extract_job_id": "",
            },
            "query_trace": {
                "query_run_id": query_run_id,
                "method": "metadata_only_degraded",
                "winner": "",
                "stage_ms": {"total": 0.0},
            },
            "attribution": {"providers": []},
        },
    }


def _configured_vlm_model(config_dir: Path) -> str:
    try:
        path = config_dir / "user.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    plugins_cfg = raw.get("plugins", {}) if isinstance(raw, dict) else {}
    settings = plugins_cfg.get("settings", {}) if isinstance(plugins_cfg, dict) else {}
    vllm = settings.get("builtin.vlm.vllm_localhost", {}) if isinstance(settings, dict) else {}
    model = str(vllm.get("model") or "").strip() if isinstance(vllm, dict) else ""
    return model


def _configured_vlm_api_key(config_dir: Path) -> str:
    try:
        path = config_dir / "user.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    plugins_cfg = raw.get("plugins", {}) if isinstance(raw, dict) else {}
    settings = plugins_cfg.get("settings", {}) if isinstance(plugins_cfg, dict) else {}
    vllm = settings.get("builtin.vlm.vllm_localhost", {}) if isinstance(settings, dict) else {}
    api_key = str(vllm.get("api_key") or "").strip() if isinstance(vllm, dict) else ""
    return api_key


def _display(result: dict[str, Any]) -> tuple[str, list[str]]:
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    display = answer.get("display", {}) if isinstance(answer.get("display", {}), dict) else {}
    summary = str(display.get("summary") or answer.get("summary") or "").strip()
    bullets_raw = display.get("bullets", []) if isinstance(display.get("bullets", []), list) else []
    bullets = [str(x).strip() for x in bullets_raw if str(x).strip()]
    return summary, bullets


def _confidence_pct(result: dict[str, Any]) -> float | None:
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    display = answer.get("display", {}) if isinstance(answer.get("display", {}), dict) else {}
    candidate = None
    for key in ("confidence_pct", "confidence"):
        if key in display:
            candidate = display.get(key)
            break
        if key in answer:
            candidate = answer.get(key)
            break
    if candidate is None:
        return None
    try:
        value = float(candidate)
    except Exception:
        return None
    if 0.0 <= value <= 1.0:
        value *= 100.0
    return float(value)


def _canonical_signature(result: dict[str, Any], summary: str, bullets: list[str]) -> str:
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    display = answer.get("display", {}) if isinstance(answer.get("display", {}), dict) else {}
    processing = result.get("processing", {}) if isinstance(result.get("processing", {}), dict) else {}
    trace = processing.get("query_trace", {}) if isinstance(processing.get("query_trace", {}), dict) else {}
    hard_vlm = processing.get("hard_vlm", {}) if isinstance(processing.get("hard_vlm", {}), dict) else {}
    payload = {
        "summary": str(summary or "").strip(),
        "bullets": [str(x).strip() for x in bullets if str(x).strip()],
        "display_fields": display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {},
        "winner": str(trace.get("winner") or ""),
        "method": str(trace.get("method") or ""),
        "hard_vlm_fields": hard_vlm.get("fields", {}) if isinstance(hard_vlm.get("fields", {}), dict) else {},
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _flatten_expected(prefix: str, value: Any, out: list[tuple[str, str]]) -> None:
    key = str(prefix or "").strip(".")
    if isinstance(value, dict):
        for k, v in value.items():
            nk = f"{key}.{k}" if key else str(k)
            _flatten_expected(nk, v, out)
        return
    if isinstance(value, list):
        for idx, item in enumerate(value):
            nk = f"{key}[{idx}]"
            _flatten_expected(nk, item, out)
        return
    text = str(value).strip()
    if text:
        out.append((key, text))


def _path_tokens(path: str) -> list[str]:
    tokens: list[str] = []
    buf = ""
    i = 0
    while i < len(path):
        ch = path[i]
        if ch == ".":
            if buf:
                tokens.append(buf)
                buf = ""
            i += 1
            continue
        if ch == "[":
            if buf:
                tokens.append(buf)
                buf = ""
            j = path.find("]", i + 1)
            if j <= i:
                tokens.append(path[i + 1 :].strip())
                break
            tokens.append(path[i + 1 : j].strip())
            i = j + 1
            continue
        buf += ch
        i += 1
    if buf:
        tokens.append(buf)
    return [tok for tok in tokens if tok]


def _resolve_path(payload: Any, path: str) -> tuple[bool, Any]:
    cur = payload
    for raw in _path_tokens(path):
        if isinstance(cur, list):
            try:
                idx = int(raw)
            except Exception:
                return False, None
            if idx < 0 or idx >= len(cur):
                return False, None
            cur = cur[idx]
            continue
        if isinstance(cur, dict):
            if raw not in cur:
                return False, None
            cur = cur.get(raw)
            continue
        return False, None
    return True, cur


def _to_haystack(result: dict[str, Any], summary: str, bullets: list[str]) -> str:
    return "\n".join(
        [
            str(summary or ""),
            "\n".join(str(x or "") for x in bullets),
            json.dumps(result, sort_keys=True),
        ]
    ).casefold()


def _is_support_line(text: str) -> bool:
    low = str(text or "").strip().casefold()
    return low.startswith("support:") or low.startswith("source:")


def _core_answer_surface(summary: str, bullets: list[str]) -> str:
    core_bullets = [str(x or "").strip() for x in bullets if str(x or "").strip() and not _is_support_line(str(x or ""))]
    return "\n".join([str(summary or ""), "\n".join(core_bullets)]).strip()


def _normalize_exact_text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _strict_quality_markers(case_id: str, summary: str, bullets: list[str]) -> list[str]:
    markers: list[str] = []
    surface = _core_answer_surface(summary, bullets)
    low = surface.casefold()
    if "..." in surface or "…" in surface:
        markers.append("truncated_ellipsis")
    # Explicit user policy: partial window outcomes are not acceptable for Q1.
    if str(case_id or "").upper() == "Q1" and (
        "partially_occluded" in low or bool(re.search(r"\bpartial(?:ly)?\b", low))
    ):
        markers.append("partial_visibility_language")
    return sorted(set(markers))


def _provider_signal_sets(provider_rows: list[dict[str, Any]]) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    positive_provider_ids: list[str] = []
    non_disallowed_positive_ids: list[str] = []
    disallowed_active: list[dict[str, Any]] = []
    for row in provider_rows:
        if not isinstance(row, dict):
            continue
        provider_id = str(row.get("provider_id") or "").strip()
        if not provider_id:
            continue
        contribution_bp = int(row.get("contribution_bp", 0) or 0)
        claim_count = int(row.get("claim_count", 0) or 0)
        citation_count = int(row.get("citation_count", 0) or 0)
        if contribution_bp > 0:
            positive_provider_ids.append(provider_id)
            if provider_id not in STRICT_DISALLOWED_ANSWER_PROVIDERS:
                non_disallowed_positive_ids.append(provider_id)
        if provider_id in STRICT_DISALLOWED_ANSWER_PROVIDERS and (
            contribution_bp > 0 or claim_count > 0 or citation_count > 0
        ):
            disallowed_active.append(
                {
                    "provider_id": provider_id,
                    "contribution_bp": contribution_bp,
                    "claim_count": claim_count,
                    "citation_count": citation_count,
                }
            )
    return (
        sorted(set(positive_provider_ids)),
        sorted(set(non_disallowed_positive_ids)),
        disallowed_active,
    )


def _token_present(token: str, haystack: str) -> bool:
    text = str(token or "").strip()
    if not text:
        return False
    low_haystack = str(haystack or "").casefold()
    low_text = text.casefold()
    if not low_haystack:
        return False
    if low_text.isdigit():
        # Avoid false positives such as expected "16" matching "163".
        pattern = rf"(?<!\d){re.escape(low_text)}(?!\d)"
        return bool(re.search(pattern, low_haystack))
    return low_text in low_haystack


def _strict_haystack(result: dict[str, Any], summary: str, bullets: list[str]) -> str:
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    display = answer.get("display", {}) if isinstance(answer.get("display", {}), dict) else {}
    display_fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
    processing = result.get("processing", {}) if isinstance(result.get("processing", {}), dict) else {}
    hard_vlm = processing.get("hard_vlm", {}) if isinstance(processing.get("hard_vlm", {}), dict) else {}
    hard_fields = hard_vlm.get("fields", {}) if isinstance(hard_vlm.get("fields", {}), dict) else {}
    core_bullets = [str(x or "").strip() for x in bullets if str(x or "").strip() and not _is_support_line(str(x or ""))]
    strict_fields = {
        "display_fields": {k: v for k, v in display_fields.items() if str(k) != "support_snippets"},
        "hard_fields": hard_fields,
    }
    return "\n".join(
        [
            str(summary or ""),
            "\n".join(core_bullets),
            json.dumps(strict_fields, sort_keys=True),
        ]
    ).casefold()


def _box_iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    try:
        ax1 = float(a.get("x1"))
        ay1 = float(a.get("y1"))
        ax2 = float(a.get("x2"))
        ay2 = float(a.get("y2"))
        bx1 = float(b.get("x1"))
        by1 = float(b.get("y1"))
        bx2 = float(b.get("x2"))
        by2 = float(b.get("y2"))
    except Exception:
        return 0.0
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    area_a = max(1e-9, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1e-9, (bx2 - bx1) * (by2 - by1))
    union = max(1e-9, area_a + area_b - inter)
    return float(inter / union)


def _evaluate_expected(
    item: dict[str, Any],
    result: dict[str, Any],
    summary: str,
    bullets: list[str],
    *,
    strict_expected_answer: bool = False,
    enforce_true_strict: bool = False,
) -> dict[str, Any]:
    case_id = str(item.get("id") or "").strip().upper()
    expected = item.get("expected_answer")
    checks: list[dict[str, Any]] = []
    haystack = _strict_haystack(result, summary, bullets) if bool(strict_expected_answer) else _to_haystack(result, summary, bullets)
    core_surface = _core_answer_surface(summary, bullets)
    passed = True

    # Enforce that advanced visual questions are answered through the full
    # reasoning path (PromptOps + structured hard-VLM extraction), not weak
    # substring matches.
    is_q_series = bool(re.match(r"^Q(?:[1-9]|10)$", case_id))
    processing = result.get("processing", {}) if isinstance(result.get("processing", {}), dict) else {}
    metadata_only_query = bool(processing.get("metadata_only_query", False))
    promptops_used = bool(processing.get("promptops_used", False))
    hard_vlm = processing.get("hard_vlm", {}) if isinstance(processing.get("hard_vlm", {}), dict) else {}
    hard_fields = hard_vlm.get("fields", {}) if isinstance(hard_vlm.get("fields", {}), dict) else {}
    structured_hard_keys = [
        str(k)
        for k, v in hard_fields.items()
        if str(k) != "answer_text" and v not in (None, "", [], {})
    ]
    attribution = processing.get("attribution", {}) if isinstance(processing.get("attribution", {}), dict) else {}
    provider_rows = attribution.get("providers", []) if isinstance(attribution.get("providers", []), list) else []
    synth_in_path = any(
        isinstance(p, dict) and str(p.get("provider_id") or "") == "builtin.answer.synth_vllm_localhost"
        for p in provider_rows
    )
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    display = answer.get("display", {}) if isinstance(answer.get("display", {}), dict) else {}
    display_fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
    metadata_structured = bool(display_fields)
    if bool(strict_expected_answer) and bool(enforce_true_strict):
        quality_markers = _strict_quality_markers(case_id, summary, bullets)
        quality_ok = len(quality_markers) == 0
        checks.append(
            {
                "type": "strict_quality",
                "key": "no_partial_or_truncated_surface",
                "required": True,
                "present": bool(quality_ok),
                "markers": quality_markers,
            }
        )
        if not quality_ok:
            passed = False
        positive_provider_ids, non_disallowed_positive_ids, disallowed_active = _provider_signal_sets(provider_rows)
        provider_checks = [
            ("positive_provider_contribution", bool(positive_provider_ids), {"provider_ids": positive_provider_ids}),
            (
                "non_disallowed_positive_provider_contribution",
                bool(non_disallowed_positive_ids),
                {"provider_ids": non_disallowed_positive_ids},
            ),
            (
                "disallowed_answer_provider_activity",
                len(disallowed_active) == 0,
                {"offenders": disallowed_active},
            ),
        ]
        for key, ok, details in provider_checks:
            checks.append(
                {
                    "type": "pipeline_enforcement",
                    "key": key,
                    "required": True,
                    "present": bool(ok),
                    **details,
                }
            )
            if not ok:
                passed = False
    if bool(strict_expected_answer) and is_q_series:
        if "indeterminate" in str(summary or "").casefold():
            checks.append(
                {
                    "type": "strict_quality",
                    "key": "summary_not_indeterminate",
                    "required": True,
                    "present": False,
                }
            )
            passed = False
        else:
            checks.append(
                {
                    "type": "strict_quality",
                    "key": "summary_not_indeterminate",
                    "required": True,
                    "present": True,
                }
            )

    if is_q_series:
        if metadata_only_query:
            q_checks = [
                ("metadata_only_query", metadata_only_query),
                ("promptops_used", promptops_used),
                ("metadata_structured_display", metadata_structured),
            ]
        else:
            q_checks = [
                ("promptops_used", promptops_used),
                ("hard_vlm_structured", bool(structured_hard_keys)),
                ("synth_provider_in_path", synth_in_path),
            ]
        for key, ok in q_checks:
            checks.append(
                {
                    "type": "pipeline_enforcement",
                    "key": key,
                    "required": True,
                    "present": bool(ok),
                    "structured_keys": structured_hard_keys if key == "hard_vlm_structured" else None,
                }
            )
            if not ok:
                passed = False

    exact_summary = str(item.get("expected_exact_summary") or "").strip()
    if exact_summary:
        ok = bool(_normalize_exact_text(summary) == _normalize_exact_text(exact_summary))
        checks.append(
            {
                "type": "exact_summary",
                "key": "expected_exact_summary",
                "expected": exact_summary,
                "actual": str(summary or ""),
                "match": ok,
            }
        )
        if not ok:
            passed = False

    exact_surface = str(item.get("expected_exact_surface") or "").strip()
    if exact_surface:
        ok = bool(_normalize_exact_text(core_surface) == _normalize_exact_text(exact_surface))
        checks.append(
            {
                "type": "exact_surface",
                "key": "expected_exact_surface",
                "expected": exact_surface,
                "actual": str(core_surface or ""),
                "match": ok,
            }
        )
        if not ok:
            passed = False

    contains_all = item.get("expected_contains_all", [])
    if isinstance(contains_all, list):
        for idx, token in enumerate(contains_all):
            text = str(token).strip()
            if not text:
                continue
            ok = _token_present(text, haystack)
            checks.append({"type": "contains_all", "key": f"contains_all[{idx}]", "expected": text, "present": bool(ok)})
            if not ok:
                passed = False

    contains_any = item.get("expected_contains_any", [])
    if isinstance(contains_any, list) and contains_any:
        any_ok = False
        for token in contains_any:
            text = str(token).strip()
            if text and _token_present(text, haystack):
                any_ok = True
                break
        checks.append(
            {
                "type": "contains_any",
                "key": "contains_any",
                "expected": [str(x).strip() for x in contains_any if str(x).strip()],
                "present": bool(any_ok),
            }
        )
        if not any_ok:
            passed = False

    path_checks = item.get("expected_paths", [])
    if isinstance(path_checks, list):
        for idx, spec in enumerate(path_checks):
            if not isinstance(spec, dict):
                continue
            path = str(spec.get("path") or "").strip()
            if not path:
                continue
            exists, value = _resolve_path(result, path)
            check_row: dict[str, Any] = {"type": "path", "key": f"expected_paths[{idx}]", "path": path, "present": bool(exists)}
            if not exists:
                checks.append(check_row)
                passed = False
                continue
            if "equals" in spec:
                expected_value = spec.get("equals")
                ok = value == expected_value
                check_row["equals"] = expected_value
                check_row["actual"] = value
                check_row["match"] = bool(ok)
                if not ok:
                    passed = False
            if "contains" in spec:
                expected_text = str(spec.get("contains") or "").strip()
                actual_text = str(value or "")
                ok = bool(expected_text) and expected_text.casefold() in actual_text.casefold()
                check_row["contains"] = expected_text
                check_row["actual"] = actual_text
                check_row["match"] = bool(ok)
                if not ok:
                    passed = False
            checks.append(check_row)

    if isinstance(expected, dict):
        answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
        display = answer.get("display", {}) if isinstance(answer.get("display", {}), dict) else {}
        display_fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
        hard_vlm = processing.get("hard_vlm", {}) if isinstance(processing.get("hard_vlm", {}), dict) else {}
        hard_fields = hard_vlm.get("fields", {}) if isinstance(hard_vlm.get("fields", {}), dict) else {}

        # Special tolerance check for normalized button boxes (H10 contract).
        has_box_expectation = all(
            isinstance(expected.get(name), dict) and {"x1", "y1", "x2", "y2"} <= set((expected.get(name) or {}).keys())
            for name in ("COMPLETE", "VIEW_DETAILS")
        )
        if has_box_expectation:
            tol = 0.60
            src_candidates: list[tuple[str, dict[str, Any]]] = [
                ("display.fields", display_fields if isinstance(display_fields, dict) else {}),
                ("hard_vlm.fields", hard_fields if isinstance(hard_fields, dict) else {}),
            ]
            for box_name in ("COMPLETE", "VIEW_DETAILS"):
                expected_box = expected.get(box_name) if isinstance(expected.get(box_name), dict) else {}
                best_iou = 0.0
                best_src = ""
                best_actual: Any = None
                for src_name, src in src_candidates:
                    box_val = src.get(box_name) if isinstance(src, dict) else None
                    if isinstance(box_val, str):
                        try:
                            box_val = json.loads(box_val)
                        except Exception:
                            box_val = None
                    if not isinstance(box_val, dict):
                        continue
                    iou = _box_iou(box_val, expected_box)
                    if iou > best_iou:
                        best_iou = iou
                        best_src = src_name
                        best_actual = box_val
                ok = bool(best_iou >= tol)
                checks.append(
                    {
                        "type": "expected_answer",
                        "mode": "iou_tolerance",
                        "key": box_name,
                        "source": best_src,
                        "expected": expected_box,
                        "actual": best_actual,
                        "iou": float(best_iou),
                        "threshold": float(tol),
                        "match": ok,
                    }
                )
                if not ok:
                    passed = False

        flat: list[tuple[str, str]] = []
        _flatten_expected("", expected, flat)
        if has_box_expectation:
            flat = [item for item in flat if not (item[0].startswith("COMPLETE.") or item[0].startswith("VIEW_DETAILS."))]

        def _norm(value: Any) -> str:
            if isinstance(value, (dict, list)):
                return json.dumps(value, sort_keys=True, separators=(",", ":"))
            return str(value).strip()

        for key, token in flat:
            expected_norm = _norm(token)
            found = False
            actual_value: Any = None
            for source_name, source in (("display.fields", display_fields), ("hard_vlm.fields", hard_fields)):
                if not isinstance(source, dict) or not source:
                    continue
                exists, value = _resolve_path(source, key)
                if exists:
                    found = True
                    actual_value = value
                    check_ok = _norm(value).casefold() == expected_norm.casefold()
                    checks.append(
                        {
                            "type": "expected_answer",
                            "mode": "structured_exact",
                            "source": source_name,
                            "key": key,
                            "expected": token,
                            "actual": value,
                            "match": bool(check_ok),
                        }
                    )
                    if not check_ok:
                        passed = False
                    break
                # Flat key fallback for fields dicts.
                if key in source:
                    found = True
                    actual_value = source.get(key)
                    check_ok = _norm(actual_value).casefold() == expected_norm.casefold()
                    checks.append(
                        {
                            "type": "expected_answer",
                            "mode": "structured_exact",
                            "source": source_name,
                            "key": key,
                            "expected": token,
                            "actual": actual_value,
                            "match": bool(check_ok),
                        }
                    )
                    if not check_ok:
                        passed = False
                    break
            if found:
                continue
            if strict_expected_answer:
                # Do not silently pass based on substring matches in free-form text.
                checks.append(
                    {
                        "type": "expected_answer",
                        "mode": "missing_structured_path",
                        "key": key,
                        "expected": token,
                        "actual": actual_value,
                        "match": False,
                    }
                )
                passed = False
            else:
                ok = _token_present(str(token or ""), haystack)
                checks.append(
                    {
                        "type": "expected_answer",
                        "mode": "contains_fallback",
                        "key": key,
                        "expected": token,
                        "present": bool(ok),
                    }
                )
                if not ok:
                    passed = False

    if bool(strict_expected_answer) and is_q_series and case_id == "Q9":
        expected_red = 8
        expected_green = 16
        summary_low = str(summary or "").casefold()
        parsed_counts: dict[str, int] = {}
        count_match = re.search(
            r"count_red\s*=\s*(\d+)\D+count_green\s*=\s*(\d+)\D+count_other\s*=\s*(\d+)",
            summary_low,
        )
        if count_match:
            parsed_counts = {
                "red_count": int(count_match.group(1)),
                "green_count": int(count_match.group(2)),
                "other_count": int(count_match.group(3)),
            }
        if not parsed_counts:
            display_fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
            try:
                parsed_counts = {
                    "red_count": int(display_fields.get("red_count") or 0),
                    "green_count": int(display_fields.get("green_count") or 0),
                    "other_count": int(display_fields.get("other_count") or 0),
                }
            except Exception:
                parsed_counts = {}
        red_ok = bool(parsed_counts.get("red_count") == expected_red)
        green_ok = bool(parsed_counts.get("green_count") == expected_green)
        checks.append(
            {
                "type": "strict_numeric",
                "key": "q9_red_count",
                "expected": expected_red,
                "actual": parsed_counts.get("red_count"),
                "match": red_ok,
            }
        )
        checks.append(
            {
                "type": "strict_numeric",
                "key": "q9_green_count",
                "expected": expected_green,
                "actual": parsed_counts.get("green_count"),
                "match": green_ok,
            }
        )
        if not red_ok or not green_ok:
            passed = False

    if not checks:
        return {"evaluated": False, "passed": None, "checks": []}

    return {"evaluated": True, "passed": bool(passed), "checks": checks}


def _case_requires_vlm(item: dict[str, Any]) -> bool:
    raw = item.get("requires_vlm")
    if isinstance(raw, bool):
        return bool(raw)
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        value = raw.strip().casefold()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
    # Advanced Q/H suites are VLM-first by default unless explicitly disabled.
    case_id = str(item.get("id") or "").strip()
    return bool(re.match(r"^(?:Q(?:[1-9]|10)|H(?:[1-9]|10)|GQ(?:[1-9]|1[0-9]|20))$", case_id, re.IGNORECASE))


def _probe_vllm_stability(
    *,
    checks: int,
    interval_ms: float,
) -> dict[str, Any]:
    required = max(1, int(checks))
    wait_s = max(0.0, float(interval_ms) / 1000.0)
    samples: list[dict[str, Any]] = []
    consecutive_ok = 0
    for idx in range(required):
        if idx > 0 and wait_s > 0:
            time.sleep(wait_s)
        sample = check_external_vllm_ready(
            require_completion=True,
            auto_recover=False,
            retries=1,
        )
        sample_row = {
            "attempt": idx + 1,
            "ok": bool(sample.get("ok", False)),
            "error": str(sample.get("error") or ""),
            "selected_model": str(sample.get("selected_model") or ""),
        }
        samples.append(sample_row)
        if sample_row["ok"]:
            consecutive_ok += 1
        else:
            consecutive_ok = 0
            break
    return {
        "ok": bool(consecutive_ok >= required),
        "required_checks": int(required),
        "consecutive_ok": int(consecutive_ok),
        "samples": samples,
    }


def main(argv: list[str] | None = None) -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="", help="Path to report.json (defaults to latest single-image report).")
    parser.add_argument("--cases", default="docs/query_eval_cases_advanced20.json", help="Path to advanced case list.")
    parser.add_argument("--profile", default="config/profiles/golden_full.json", help="Expected profile JSON path.")
    parser.add_argument("--output", default="", help="Optional output file path.")
    parser.add_argument("--strict-all", action="store_true", help="Exit non-zero unless all rows are strictly evaluated and pass.")
    parser.add_argument(
        "--allow-vllm-unavailable",
        action="store_true",
        help="Continue execution even when external vLLM health check fails.",
    )
    parser.add_argument(
        "--skip-vllm-unstable",
        dest="skip_vllm_unstable",
        action="store_true",
        default=True,
        help="Mark VLM-required cases as skipped while VLM preflight/stability is unhealthy (default: true).",
    )
    parser.add_argument(
        "--fail-on-vllm-unstable",
        dest="skip_vllm_unstable",
        action="store_false",
        help="Fail closed instead of skipping VLM-required cases when VLM is unstable/unavailable.",
    )
    parser.add_argument(
        "--vlm-stability-checks",
        type=int,
        default=_env_int("AUTOCAPTURE_VLM_STABILITY_CHECKS", 2),
        help="Require this many consecutive successful completion probes before treating VLM as stable.",
    )
    parser.add_argument(
        "--vlm-stability-interval-ms",
        type=float,
        default=_env_float("AUTOCAPTURE_VLM_STABILITY_INTERVAL_MS", 750.0),
        help="Delay between VLM stability probes in milliseconds.",
    )
    parser.add_argument("--query-timeout-s", type=float, default=90.0, help="Per-query timeout in seconds.")
    parser.add_argument("--lock-retries", type=int, default=4, help="Retries for transient instance_lock_held errors.")
    parser.add_argument("--lock-retry-wait-ms", type=float, default=250.0, help="Base wait between lock retries in ms.")
    parser.add_argument("--repro-runs", type=int, default=0, help="Repeat each query this many times for determinism checks (0=use contract default).")
    parser.add_argument("--metadata-only", action="store_true", help="Do not pass screenshot path at query time; evaluate from extracted records only.")
    parser.add_argument(
        "--confidence-drift-tolerance-pct",
        type=float,
        default=1.0,
        help="Maximum allowed absolute confidence drift (percentage points) across repro runs.",
    )
    args = parser.parse_args(argv)
    _emit_progress(
        "start",
        strict_all=bool(args.strict_all),
        metadata_only=bool(args.metadata_only),
        query_timeout_s=float(args.query_timeout_s),
        lock_retries=int(args.lock_retries),
    )

    report_path = Path(str(args.report or "").strip()) if str(args.report or "").strip() else _latest_report(root)
    if not report_path.exists():
        print(json.dumps({"ok": False, "error": "report_not_found", "report": str(report_path)}))
        return 2
    report_raw = report_path.read_text(encoding="utf-8")
    report = json.loads(report_raw)
    source_report_sha256 = hashlib.sha256(report_raw.encode("utf-8")).hexdigest()
    source_report_run_id = str(report.get("run_id") or "").strip()
    cfg = str(report.get("config_dir") or "").strip()
    data = str(report.get("data_dir") or "").strip()
    if not cfg or not data:
        print(json.dumps({"ok": False, "error": "report_missing_config_or_data", "report": str(report_path)}))
        return 2
    if not str(os.environ.get("AUTOCAPTURE_VLM_API_KEY") or "").strip():
        api_key = _configured_vlm_api_key(Path(cfg))
        if api_key:
            os.environ["AUTOCAPTURE_VLM_API_KEY"] = api_key
    base_url_raw = str(os.environ.get("AUTOCAPTURE_VLM_BASE_URL") or "").strip() or "http://127.0.0.1:8000/v1"
    try:
        os.environ["AUTOCAPTURE_VLM_BASE_URL"] = enforce_external_vllm_base_url(base_url_raw)
    except Exception:
        os.environ["AUTOCAPTURE_VLM_BASE_URL"] = "http://127.0.0.1:8000/v1"
    os.environ.setdefault("AUTOCAPTURE_VLM_MODEL", "internvl3_5_8b")
    os.environ.setdefault("AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S", "12")
    os.environ.setdefault("AUTOCAPTURE_VLM_PREFLIGHT_RETRIES", "3")
    os.environ.setdefault("AUTOCAPTURE_VLM_MAX_INFLIGHT", "1")
    os.environ.setdefault(
        "AUTOCAPTURE_VLM_ORCHESTRATOR_CMD",
        "bash /mnt/d/projects/hypervisor/tools/wsl/start_internvl35_8b_with_watch.sh",
    )
    plugins = report.get("plugins", {}) if isinstance(report.get("plugins", {}), dict) else {}
    load_report = plugins.get("load_report", {}) if isinstance(plugins.get("load_report", {}), dict) else {}
    required_gate = plugins.get("required_gate", {}) if isinstance(plugins.get("required_gate", {}), dict) else {}
    if load_report and required_gate and not bool(required_gate.get("ok", False)):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "required_plugin_gate_failed",
                    "report": str(report_path),
                    "required_gate": required_gate,
                }
            )
        )
        return 2
    if args.strict_all and bool(args.allow_vllm_unavailable):
        print(json.dumps({"ok": False, "error": "strict_mode_disallows_allow-vllm-unavailable"}))
        return 2
    if args.strict_all and not bool(args.metadata_only):
        print(json.dumps({"ok": False, "error": "strict_mode_requires_metadata_only"}))
        return 2
    if args.strict_all:
        # Strict mode must fail closed on VLM instability; skipping is non-shippable.
        args.skip_vllm_unstable = False

    profile_path = (root / str(args.profile)).resolve() if not Path(str(args.profile)).is_absolute() else Path(str(args.profile))
    if args.strict_all and not profile_path.exists():
        print(json.dumps({"ok": False, "error": "profile_not_found", "profile": str(profile_path)}))
        return 2
    profile_sha = hashlib.sha256(profile_path.read_bytes()).hexdigest() if profile_path.exists() else ""
    report_profile_sha = str(report.get("profile_sha256") or "").strip()
    if args.strict_all and not report_profile_sha:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "report_missing_profile_sha256",
                    "report": str(report_path),
                }
            )
        )
        return 2
    if args.strict_all and report_profile_sha and report_profile_sha != profile_sha:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "profile_checksum_mismatch",
                    "report_profile_sha256": report_profile_sha,
                    "expected_profile_sha256": profile_sha,
                    "profile": str(profile_path),
                }
            )
        )
        return 2
    determinism_raw = report.get("determinism_contract", {}) if isinstance(report.get("determinism_contract", {}), dict) else {}
    determinism = {
        "timezone": str(determinism_raw.get("timezone") or "UTC"),
        "lang": str(determinism_raw.get("lang") or "C.UTF-8"),
        "pythonhashseed": str(determinism_raw.get("pythonhashseed") or "0"),
    }
    repro_runs = int(args.repro_runs or 0)
    if repro_runs <= 0 and bool(args.metadata_only):
        repro_runs = 1
    elif repro_runs <= 0:
        repro_runs = int(determinism_raw.get("repro_runs") or (3 if args.strict_all else 1))
    repro_runs = max(1, repro_runs)

    os.environ.setdefault("AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S", "45")
    os.environ.setdefault("AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_MAX_S", "120")
    os.environ.setdefault("AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_SCALE", "1.5")
    os.environ.setdefault("AUTOCAPTURE_VLM_PREFLIGHT_RETRIES", "6")
    _emit_progress("vlm.preflight.begin", strict_all=bool(args.strict_all))
    preflight_t0 = time.monotonic()
    metadata_only_mode = bool(args.metadata_only)
    if metadata_only_mode:
        vllm_status = {
            "ok": True,
            "metadata_only_mode": True,
            "preflight_skipped": True,
            "selected_model": "",
        }
    else:
        preflight_retries_override = 1 if bool(args.skip_vllm_unstable) else None
        preflight_completion_timeout_override = 12.0 if bool(args.skip_vllm_unstable) else None
        vllm_status = check_external_vllm_ready(
            require_completion=True,
            retries=preflight_retries_override,
            timeout_completion_s=preflight_completion_timeout_override,
        )
    _emit_progress(
        "vlm.preflight.done",
        ok=bool(vllm_status.get("ok", False)),
        latency_ms=int((time.monotonic() - preflight_t0) * 1000),
        selected_model=str(vllm_status.get("selected_model") or ""),
    )
    if metadata_only_mode:
        stability = {
            "ok": True,
            "required_checks": 0,
            "consecutive_ok": 0,
            "samples": [],
            "metadata_only_bypass": True,
        }
    elif not bool(vllm_status.get("ok", False)) and bool(args.skip_vllm_unstable):
        stability = {
            "ok": False,
            "required_checks": max(1, int(args.vlm_stability_checks)),
            "consecutive_ok": 0,
            "samples": [],
            "skipped_after_preflight_failure": True,
        }
    else:
        stability = _probe_vllm_stability(
            checks=max(1, int(args.vlm_stability_checks)),
            interval_ms=float(args.vlm_stability_interval_ms),
        )
    vllm_status["stability"] = stability
    vllm_unstable = (not bool(vllm_status.get("ok", False))) or (not bool(stability.get("ok", False)))
    skip_vlm_cases = False
    if vllm_unstable:
        reason = str(vllm_status.get("error") or "vlm_unavailable_or_unstable")
        vllm_status["degraded_mode"] = True
        vllm_status["unstable_reason"] = reason
        if metadata_only_mode:
            skip_vlm_cases = False
            vllm_status["metadata_only_bypass"] = True
        elif bool(args.skip_vllm_unstable) or bool(args.allow_vllm_unavailable):
            skip_vlm_cases = True
        else:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "external_vllm_unavailable",
                        "message": "External vLLM preflight/stability failed.",
                        "orchestrator_cmd": str(vllm_status.get("orchestrator_cmd") or os.environ.get("AUTOCAPTURE_VLM_ORCHESTRATOR_CMD") or ""),
                        "vllm_status": vllm_status,
                    }
                )
            )
            return 2

    cases_path = (root / str(args.cases)).resolve() if not Path(str(args.cases)).is_absolute() else Path(str(args.cases))
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    items = [item for item in cases if isinstance(item, dict)]
    rows: list[dict[str, Any]] = []
    passed_total = 0
    evaluated_total = 0
    skipped_total = 0
    _emit_progress("cases.loaded", count=int(len(items)), cases_path=str(cases_path))

    for item in items:
        case_id = str(item.get("id") or "")
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        requires_vlm = _case_requires_vlm(item)
        if skip_vlm_cases and requires_vlm:
            skip_reason = str(vllm_status.get("unstable_reason") or "vlm_unavailable_or_unstable")
            eval_result = {
                "evaluated": False,
                "passed": None,
                "skipped": True,
                "skip_reason": f"vlm_unstable:{skip_reason}",
                "checks": [
                    {
                        "type": "skip_gate",
                        "key": "vlm_stability",
                        "required": True,
                        "present": False,
                        "reason": f"vlm_unstable:{skip_reason}",
                    }
                ],
            }
            rows.append(
                {
                    "id": case_id,
                    "question": question,
                    "ok": False,
                    "passed": False,
                    "skipped": True,
                    "skip_reason": str(eval_result.get("skip_reason") or ""),
                    "requires_vlm": bool(requires_vlm),
                    "error": "skipped_vlm_unstable",
                    "answer_state": "skipped",
                    "summary": "",
                    "bullets": [],
                    "query_run_id": "",
                    "method": "skip",
                    "winner": "",
                    "stage_ms": {},
                    "providers": [],
                    "hard_vlm": {},
                    "source_report": str(report_path),
                    "source_report_sha256": str(source_report_sha256),
                    "source_report_run_id": str(source_report_run_id),
                    "determinism_repro": {
                        "type": "determinism_repro",
                        "runs": int(repro_runs),
                        "match": None,
                        "signatures": [],
                        "confidence_samples_pct": [],
                        "confidence_drift_max_pct": None,
                        "confidence_drift_tolerance_pct": round(float(max(0.0, args.confidence_drift_tolerance_pct)), 3),
                        "errors": ["skipped_vlm_unstable"],
                    },
                    "expected_eval": eval_result,
                }
            )
            skipped_total += 1
            _emit_progress(
                "case.skipped",
                case_id=case_id,
                reason=str(eval_result.get("skip_reason") or ""),
            )
            continue
        _emit_progress("case.begin", case_id=case_id, question=question)
        case_t0 = time.monotonic()
        image_path = str(report.get("image_path") or "").strip()
        if image_path and not Path(image_path).is_absolute():
            image_path = str((root / image_path).resolve())
        query_image_path = "" if bool(args.metadata_only) else image_path
        result = _run_query(
            root,
            cfg=cfg,
            data=data,
            query=question,
            image_path=query_image_path,
            timeout_s=float(args.query_timeout_s),
            lock_retries=int(args.lock_retries),
            lock_retry_wait_s=float(args.lock_retry_wait_ms) / 1000.0,
            determinism=determinism,
            metadata_only=bool(args.metadata_only),
        )
        if bool(args.metadata_only) and (not bool(result.get("ok", False))) and str(case_id or "").upper().startswith("GQ"):
            result = _contractize_query_failure(result, query=question, case_id=str(case_id or "GQ"))
        summary, bullets = _display(result)
        signatures = [_canonical_signature(result, summary, bullets)]
        confidence_samples: list[float] = []
        conf0 = _confidence_pct(result)
        if conf0 is not None:
            confidence_samples.append(conf0)
        repro_ok = True
        repro_errors: list[str] = []
        for idx in range(1, repro_runs):
            rerun = _run_query(
                root,
                cfg=cfg,
                data=data,
                query=question,
                image_path=query_image_path,
                timeout_s=float(args.query_timeout_s),
                lock_retries=int(args.lock_retries),
                lock_retry_wait_s=float(args.lock_retry_wait_ms) / 1000.0,
                determinism=determinism,
                metadata_only=bool(args.metadata_only),
            )
            if bool(args.metadata_only) and (not bool(rerun.get("ok", False))) and str(case_id or "").upper().startswith("GQ"):
                rerun = _contractize_query_failure(rerun, query=question, case_id=str(case_id or "GQ"))
            rsum, rbul = _display(rerun)
            signatures.append(_canonical_signature(rerun, rsum, rbul))
            conf = _confidence_pct(rerun)
            if conf is not None:
                confidence_samples.append(conf)
            if not bool(rerun.get("ok", False)):
                repro_ok = False
                repro_errors.append(str(rerun.get("error") or "rerun_failed"))
        if len(set(signatures)) != 1:
            repro_ok = False
        confidence_tolerance = max(0.0, float(args.confidence_drift_tolerance_pct))
        confidence_drift_max = 0.0
        if len(confidence_samples) >= 2:
            base = confidence_samples[0]
            confidence_drift_max = max(abs(sample - base) for sample in confidence_samples[1:])
            if confidence_drift_max > confidence_tolerance:
                repro_ok = False
                repro_errors.append(
                    f"confidence_drift_exceeded:{round(confidence_drift_max,3)}>{round(confidence_tolerance,3)}"
                )
        eval_result = _evaluate_expected(
            item,
            result,
            summary,
            bullets,
            strict_expected_answer=True,
            enforce_true_strict=bool(args.strict_all),
        )
        repro_check = {
            "type": "determinism_repro",
            "runs": int(repro_runs),
            "match": bool(repro_ok),
            "signatures": signatures,
            "confidence_samples_pct": [round(float(x), 3) for x in confidence_samples],
            "confidence_drift_max_pct": round(float(confidence_drift_max), 3),
            "confidence_drift_tolerance_pct": round(float(confidence_tolerance), 3),
            "errors": repro_errors,
        }
        if bool(eval_result.get("evaluated", False)):
            checks = eval_result.get("checks", [])
            if isinstance(checks, list):
                checks.append(repro_check)
            if not repro_ok:
                eval_result["passed"] = False
        else:
            eval_result = {"evaluated": True, "passed": bool(repro_ok), "checks": [repro_check]}
        if bool(eval_result.get("evaluated", False)):
            evaluated_total += 1
            if bool(eval_result.get("passed", False)):
                passed_total += 1
        processing = result.get("processing", {}) if isinstance(result.get("processing", {}), dict) else {}
        trace = processing.get("query_trace", {}) if isinstance(processing.get("query_trace", {}), dict) else {}
        attribution = processing.get("attribution", {}) if isinstance(processing.get("attribution", {}), dict) else {}
        answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
        rows.append(
            {
                "id": case_id,
                "question": question,
                "ok": bool(result.get("ok", False)),
                "passed": bool(eval_result.get("passed", False)) if bool(eval_result.get("evaluated", False)) else False,
                "skipped": False,
                "skip_reason": "",
                "requires_vlm": bool(requires_vlm),
                "error": str(result.get("error") or ""),
                "answer_state": str(answer.get("state") or ""),
                "summary": summary,
                "bullets": bullets,
                "query_run_id": str(trace.get("query_run_id") or ""),
                "method": str(trace.get("method") or ""),
                "winner": str(trace.get("winner") or ""),
                "stage_ms": trace.get("stage_ms", {}),
                "providers": attribution.get("providers", []),
                "hard_vlm": processing.get("hard_vlm", {}),
                "source_report": str(report_path),
                "source_report_sha256": str(source_report_sha256),
                "source_report_run_id": str(source_report_run_id),
                "determinism_repro": repro_check,
                "expected_eval": eval_result,
            }
        )
        _emit_progress(
            "case.done",
            case_id=case_id,
            ok=bool(result.get("ok", False)),
            passed=bool(eval_result.get("passed", False)) if bool(eval_result.get("evaluated", False)) else False,
            latency_ms=int((time.monotonic() - case_t0) * 1000),
            winner=str(trace.get("winner") or ""),
        )

    evaluated_failed = int(max(0, evaluated_total - passed_total))
    all_rows_passed = bool(evaluated_failed == 0 and (int(evaluated_total) + int(skipped_total) == int(len(rows))))
    strict_failure_reasons: list[str] = []
    if bool(args.strict_all):
        if int(evaluated_total) <= 0:
            strict_failure_reasons.append("strict_evaluated_zero")
        if int(skipped_total) > 0:
            strict_failure_reasons.append("strict_skipped_nonzero")
        if int(evaluated_failed) > 0:
            strict_failure_reasons.append("strict_failed_nonzero")
        if int(evaluated_total) != int(len(rows)):
            strict_failure_reasons.append("strict_evaluated_mismatch")
    strict_ok = len(strict_failure_reasons) == 0
    out = {
        "ok": bool(all_rows_passed and (strict_ok if bool(args.strict_all) else True)),
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "report": str(report_path),
        "source_report": str(report_path),
        "source_report_sha256": str(source_report_sha256),
        "source_report_run_id": str(source_report_run_id),
        "config_dir": cfg,
        "data_dir": data,
        "vllm_status": vllm_status,
        "profile_sha256_expected": profile_sha,
        "profile_sha256_report": report_profile_sha,
        "repro_runs": int(repro_runs),
        "metadata_only": bool(args.metadata_only),
        "confidence_drift_tolerance_pct": float(max(0.0, args.confidence_drift_tolerance_pct)),
        "determinism": determinism,
        "evaluated_total": int(evaluated_total),
        "evaluated_passed": int(passed_total),
        "evaluated_failed": int(evaluated_failed),
        "rows_skipped": int(skipped_total),
        "skip_vlm_unstable": bool(args.skip_vllm_unstable),
        "strict_all": bool(args.strict_all),
        "strict_ok": bool(strict_ok),
        "strict_failure_reasons": [str(x) for x in strict_failure_reasons],
        "rows": rows,
    }
    case_prefix = f"advanced{len(rows)}"
    output_path = (
        Path(str(args.output or "").strip())
        if str(args.output or "").strip()
        else root / "artifacts" / "advanced10" / f"{case_prefix}_{_utc_stamp()}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    _emit_progress(
        "finish",
        ok=bool(out["ok"]),
        rows=int(len(rows)),
        evaluated_total=int(evaluated_total),
        evaluated_passed=int(passed_total),
        output=str(output_path),
    )
    print(json.dumps({"ok": True, "output": str(output_path), "rows": len(rows)}))
    if bool(args.strict_all):
        if not strict_ok:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
