#!/usr/bin/env python3
"""Run advanced question set against latest single-image run and persist results."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.inference.vllm_endpoint import EXTERNAL_VLLM_BASE_URL, check_external_vllm_ready


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


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
) -> dict[str, Any]:
    py = root / ".venv" / "bin" / "python"
    env = dict(os.environ)
    env["AUTOCAPTURE_CONFIG_DIR"] = str(cfg)
    env["AUTOCAPTURE_DATA_DIR"] = str(data)
    if str(image_path or "").strip():
        env["AUTOCAPTURE_QUERY_IMAGE_PATH"] = str(image_path).strip()
    env["AUTOCAPTURE_HARD_VLM_DEBUG"] = "1"
    env["AUTOCAPTURE_VLM_BASE_URL"] = EXTERNAL_VLLM_BASE_URL
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


def _display(result: dict[str, Any]) -> tuple[str, list[str]]:
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    display = answer.get("display", {}) if isinstance(answer.get("display", {}), dict) else {}
    summary = str(display.get("summary") or answer.get("summary") or "").strip()
    bullets_raw = display.get("bullets", []) if isinstance(display.get("bullets", []), list) else []
    bullets = [str(x).strip() for x in bullets_raw if str(x).strip()]
    return summary, bullets


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


def _evaluate_expected(item: dict[str, Any], result: dict[str, Any], summary: str, bullets: list[str]) -> dict[str, Any]:
    expected = item.get("expected_answer")
    checks: list[dict[str, Any]] = []
    haystack = _to_haystack(result, summary, bullets)
    passed = True

    contains_all = item.get("expected_contains_all", [])
    if isinstance(contains_all, list):
        for idx, token in enumerate(contains_all):
            text = str(token).strip()
            if not text:
                continue
            ok = text.casefold() in haystack
            checks.append({"type": "contains_all", "key": f"contains_all[{idx}]", "expected": text, "present": bool(ok)})
            if not ok:
                passed = False

    contains_any = item.get("expected_contains_any", [])
    if isinstance(contains_any, list) and contains_any:
        any_ok = False
        for token in contains_any:
            text = str(token).strip()
            if text and text.casefold() in haystack:
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
        flat: list[tuple[str, str]] = []
        _flatten_expected("", expected, flat)
        for key, token in flat:
            ok = str(token or "").casefold() in haystack
            checks.append({"type": "expected_answer", "key": key, "expected": token, "present": bool(ok)})
            if not ok:
                passed = False

    if not checks:
        return {"evaluated": False, "passed": None, "checks": []}

    return {"evaluated": True, "passed": bool(passed), "checks": checks}


def main(argv: list[str] | None = None) -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="", help="Path to report.json (defaults to latest single-image report).")
    parser.add_argument("--cases", default="docs/query_eval_cases_advanced20.json", help="Path to advanced case list.")
    parser.add_argument("--output", default="", help="Optional output file path.")
    parser.add_argument("--strict-all", action="store_true", help="Exit non-zero unless all rows are strictly evaluated and pass.")
    parser.add_argument(
        "--allow-vllm-unavailable",
        action="store_true",
        help="Continue execution even when external vLLM health check fails.",
    )
    parser.add_argument("--query-timeout-s", type=float, default=90.0, help="Per-query timeout in seconds.")
    parser.add_argument("--lock-retries", type=int, default=4, help="Retries for transient instance_lock_held errors.")
    parser.add_argument("--lock-retry-wait-ms", type=float, default=250.0, help="Base wait between lock retries in ms.")
    args = parser.parse_args(argv)

    report_path = Path(str(args.report or "").strip()) if str(args.report or "").strip() else _latest_report(root)
    if not report_path.exists():
        print(json.dumps({"ok": False, "error": "report_not_found", "report": str(report_path)}))
        return 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    cfg = str(report.get("config_dir") or "").strip()
    data = str(report.get("data_dir") or "").strip()
    if not cfg or not data:
        print(json.dumps({"ok": False, "error": "report_missing_config_or_data", "report": str(report_path)}))
        return 2
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

    vllm_status = check_external_vllm_ready()
    if not bool(vllm_status.get("ok", False)):
        if args.allow_vllm_unavailable:
            vllm_status["degraded_mode"] = True
        else:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "external_vllm_unavailable",
                        "message": "This repo no longer launches vLLM. Start vLLM from sidecar repo on 127.0.0.1:8000.",
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

    for item in items:
        case_id = str(item.get("id") or "")
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        result = _run_query(
            root,
            cfg=cfg,
            data=data,
            query=question,
            image_path=str(report.get("image_path") or "").strip(),
            timeout_s=float(args.query_timeout_s),
            lock_retries=int(args.lock_retries),
            lock_retry_wait_s=float(args.lock_retry_wait_ms) / 1000.0,
        )
        summary, bullets = _display(result)
        eval_result = _evaluate_expected(item, result, summary, bullets)
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
                "expected_eval": eval_result,
            }
        )

    out = {
        "ok": True,
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "report": str(report_path),
        "config_dir": cfg,
        "data_dir": data,
        "vllm_status": vllm_status,
        "evaluated_total": int(evaluated_total),
        "evaluated_passed": int(passed_total),
        "evaluated_failed": int(max(0, evaluated_total - passed_total)),
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
    print(json.dumps({"ok": True, "output": str(output_path), "rows": len(rows)}))
    if bool(args.strict_all):
        if int(evaluated_total) != int(len(rows)) or int(passed_total) != int(len(rows)):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
