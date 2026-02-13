#!/usr/bin/env python3
"""Run query against latest single-image run and capture interactive feedback."""

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
    latest_path: Path | None = None
    latest_mtime = -1.0
    if not base.exists():
        return Path("")
    for path in base.glob("*/report.json"):
        try:
            mt = path.stat().st_mtime
        except Exception:
            continue
        if mt > latest_mtime:
            latest_mtime = mt
            latest_path = path
    return latest_path or Path("")


def _run_query(root: Path, query: str, cfg: str, data: str) -> dict[str, Any]:
    py = root / ".venv" / "bin" / "python"
    env = dict(os.environ)
    env["AUTOCAPTURE_CONFIG_DIR"] = str(cfg)
    env["AUTOCAPTURE_DATA_DIR"] = str(data)
    env.setdefault("AUTOCAPTURE_HARD_VLM_DEBUG", "1")
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
        raise RuntimeError(f"query_failed: exit={proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}")
    try:
        return json.loads(proc.stdout)
    except Exception as exc:
        raise RuntimeError(f"query_output_not_json: {type(exc).__name__}: {exc}")


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


def _summary(result: dict[str, Any]) -> tuple[str, list[str]]:
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    display = answer.get("display", {}) if isinstance(answer.get("display", {}), dict) else {}
    summary = str(display.get("summary") or answer.get("summary") or "").strip()
    bullets = display.get("bullets", []) if isinstance(display.get("bullets", []), list) else []
    out = [str(item).strip() for item in bullets if str(item).strip()]
    if not summary:
        claims = answer.get("claims", []) if isinstance(answer.get("claims", []), list) else []
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            text = str(claim.get("text") or "").strip()
            if text:
                summary = text
                break
    return summary, out


def _run_feedback(
    root: Path,
    *,
    cfg: str,
    data: str,
    query: str,
    query_run_id: str,
    verdict: str,
    expected: str,
    actual: str,
    notes: str,
    plugin_fix_summary: str,
    plugin_ids: str,
    plugin_fix_files: str,
    method: str,
) -> dict[str, Any]:
    py = root / ".venv" / "bin" / "python"
    cmd = [
        str(py),
        str(root / "tools" / "query_feedback.py"),
        "--query",
        str(query),
        "--query-run-id",
        str(query_run_id),
        "--verdict",
        str(verdict),
        "--expected-answer",
        str(expected),
        "--actual-answer",
        str(actual),
        "--notes",
        str(notes),
        "--plugin-fix-summary",
        str(plugin_fix_summary),
        "--method",
        str(method),
        "--feedback-source",
        "interactive",
    ]
    if plugin_ids.strip():
        cmd.extend(["--plugin-id", plugin_ids.strip()])
    if plugin_fix_files.strip():
        cmd.extend(["--plugin-fix-file", plugin_fix_files.strip()])
    env = dict(os.environ)
    env["AUTOCAPTURE_CONFIG_DIR"] = str(cfg)
    env["AUTOCAPTURE_DATA_DIR"] = str(data)
    existing = str(env.get("PYTHONPATH") or "").strip()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{existing}" if existing else str(root)
    proc = subprocess.run(cmd, cwd=str(root), env=env, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr.strip() or proc.stdout.strip()}
    try:
        parsed = json.loads(proc.stdout or "{}")
    except Exception:
        parsed = {"ok": False, "error": "feedback_output_not_json"}
    return parsed if isinstance(parsed, dict) else {"ok": False, "error": "feedback_output_invalid"}


def _input(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", help="Query string")
    parser.add_argument("--interactive", choices=["auto", "on", "off"], default="auto")
    parser.add_argument("--verdict", default="", help="agree/disagree/partial")
    parser.add_argument("--expected", default="", help="expected/ground-truth answer")
    parser.add_argument("--notes", default="", help="review notes")
    parser.add_argument("--plugin-fix-summary", default="", help="how plugin workflow should change")
    parser.add_argument("--plugin-ids", default="", help="comma-separated plugin ids for fix")
    parser.add_argument("--plugin-fix-files", default="", help="comma-separated files changed/needed")
    args = parser.parse_args(argv)

    root = _repo_root()
    report_path = _latest_report(root)
    if not report_path.exists():
        print("ERROR: No single_image_runs report found.", file=sys.stderr)
        return 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    cfg = str(report.get("config_dir") or "").strip()
    data = str(report.get("data_dir") or "").strip()
    if not cfg or not data:
        print("ERROR: latest report missing config_dir/data_dir.", file=sys.stderr)
        return 2

    vllm_status = check_external_vllm_ready()
    if not bool(vllm_status.get("ok", False)):
        print(
            "ERROR: external vLLM unavailable at http://127.0.0.1:8000. "
            "This repo no longer starts vLLM locally; start it from the sidecar repo.",
            file=sys.stderr,
        )
        print(json.dumps(vllm_status, indent=2), file=sys.stderr)
        return 2

    result = _run_query(root, str(args.query), cfg, data)
    processing = result.get("processing", {}) if isinstance(result.get("processing", {}), dict) else {}
    query_trace = processing.get("query_trace", {}) if isinstance(processing.get("query_trace", {}), dict) else {}
    query_run_id = str(query_trace.get("query_run_id") or "").strip()
    method = str(query_trace.get("method") or "").strip()
    summary, bullets = _summary(result)

    sessions_dir = root / "artifacts" / "query_sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_path = sessions_dir / f"query_{_utc_stamp()}.json"
    session_doc = {
        "query": str(args.query),
        "query_run_id": query_run_id,
        "method": method,
        "vllm_status": vllm_status,
        "report_path": str(report_path),
        "config_dir": cfg,
        "data_dir": data,
        "result": result,
    }
    session_path.write_text(json.dumps(session_doc, indent=2, sort_keys=True), encoding="utf-8")

    print(f"answer: {summary}")
    if bullets:
        print("breakdown:")
        for bullet in bullets:
            print(f"- {bullet}")
    print(f"query_run_id: {query_run_id}")
    print(f"artifact: {session_path}")

    interactive = args.interactive
    do_prompt = bool(interactive == "on" or (interactive == "auto" and sys.stdin.isatty() and sys.stdout.isatty()))
    verdict = str(args.verdict or "").strip()
    expected = str(args.expected or "").strip()
    notes = str(args.notes or "").strip()
    plugin_fix_summary = str(args.plugin_fix_summary or "").strip()
    plugin_ids = str(args.plugin_ids or "").strip()
    plugin_fix_files = str(args.plugin_fix_files or "").strip()
    feedback = {"ok": False, "skipped": True}
    if do_prompt and not verdict:
        verdict = _input("verdict [agree/disagree/partial/skip]: ").casefold()
    if verdict and verdict != "skip":
        if do_prompt and not expected and verdict in {"disagree", "partial"}:
            expected = _input("expected answer: ")
        if do_prompt and not notes:
            notes = _input("notes (optional): ")
        if do_prompt and not plugin_fix_summary and verdict in {"disagree", "partial"}:
            plugin_fix_summary = _input("plugin fix summary (optional): ")
        if do_prompt and not plugin_ids and verdict in {"disagree", "partial"}:
            plugin_ids = _input("plugin ids (comma-separated, optional): ")
        if do_prompt and not plugin_fix_files and verdict in {"disagree", "partial"}:
            plugin_fix_files = _input("plugin files (comma-separated, optional): ")
        feedback = _run_feedback(
            root,
            cfg=cfg,
            data=data,
            query=str(args.query),
            query_run_id=query_run_id,
            verdict=verdict,
            expected=expected,
            actual=summary,
            notes=notes,
            plugin_fix_summary=plugin_fix_summary,
            plugin_ids=plugin_ids,
            plugin_fix_files=plugin_fix_files,
            method=method,
        )
        if feedback.get("ok"):
            print(f"feedback: saved ({feedback.get('path')})")
        else:
            print(f"feedback: failed ({feedback.get('error')})")
    else:
        print("feedback: skipped")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
