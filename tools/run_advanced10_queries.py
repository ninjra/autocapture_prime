#!/usr/bin/env python3
"""Run advanced question set against latest single-image run and persist results."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
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


def _run_query(root: Path, *, cfg: str, data: str, query: str, image_path: str = "") -> dict[str, Any]:
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
    proc = subprocess.run(
        [str(py), "-m", "autocapture_nx", "query", str(query)],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr.strip() or proc.stdout.strip(), "answer": {}, "processing": {}}
    try:
        out = json.loads(proc.stdout or "{}")
    except Exception as exc:
        return {"ok": False, "error": f"query_output_not_json:{type(exc).__name__}:{exc}", "answer": {}, "processing": {}}
    if not isinstance(out, dict):
        return {"ok": False, "error": "query_output_invalid", "answer": {}, "processing": {}}
    out["ok"] = True
    return out


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


def _evaluate_expected(item: dict[str, Any], result: dict[str, Any], summary: str, bullets: list[str]) -> dict[str, Any]:
    expected = item.get("expected_answer")
    if not isinstance(expected, dict):
        return {"evaluated": False, "passed": None, "checks": []}
    checks: list[dict[str, Any]] = []
    flat: list[tuple[str, str]] = []
    _flatten_expected("", expected, flat)
    haystack = "\n".join(
        [
            str(summary or ""),
            "\n".join(str(x or "") for x in bullets),
            json.dumps(result, sort_keys=True),
        ]
    ).casefold()
    passed = True
    for key, token in flat:
        ok = str(token or "").casefold() in haystack
        checks.append({"key": key, "expected": token, "present": bool(ok)})
        if not ok:
            passed = False
    return {"evaluated": True, "passed": bool(passed), "checks": checks}


def main(argv: list[str] | None = None) -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="", help="Path to report.json (defaults to latest single-image report).")
    parser.add_argument("--cases", default="docs/query_eval_cases_advanced20.json", help="Path to advanced case list.")
    parser.add_argument("--output", default="", help="Optional output file path.")
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

    vllm_status = check_external_vllm_ready()
    if not bool(vllm_status.get("ok", False)):
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
    output_path = Path(str(args.output or "").strip()) if str(args.output or "").strip() else root / "artifacts" / "advanced10" / f"advanced10_{_utc_stamp()}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output_path), "rows": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
