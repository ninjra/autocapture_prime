#!/usr/bin/env python3
"""Validate live sidecar + localhost VLM stack and emit closure artifact."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_json(cmd: list[str], *, cwd: Path) -> tuple[int, dict[str, Any], str]:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
    stdout = str(proc.stdout or "").strip()
    payload: dict[str, Any] = {}
    if stdout:
        try:
            payload = json.loads(stdout)
        except Exception:
            payload = {}
    return int(proc.returncode), payload, stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataroot", default="/mnt/d/autocapture")
    parser.add_argument("--vllm-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout-s", type=float, default=3.0)
    parser.add_argument("--max-journal-lines", type=int, default=2000)
    parser.add_argument("--output", default="artifacts/live_stack/validation_latest.json")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    py = root / ".venv" / "bin" / "python"
    python_exe = str(py if py.exists() else Path(__import__("sys").executable))

    preflight_cmd = [
        python_exe,
        str(root / "tools" / "preflight_live_stack.py"),
        "--dataroot",
        str(args.dataroot),
        "--vllm-base-url",
        str(args.vllm_base_url),
        "--timeout-s",
        str(args.timeout_s),
        "--output",
        str(root / "artifacts" / "live_stack" / "preflight_latest.json"),
    ]
    pre_rc, _pre_payload, pre_stdout = _run_json(preflight_cmd, cwd=root)
    preflight_path = root / "artifacts" / "live_stack" / "preflight_latest.json"
    preflight = {}
    if preflight_path.exists():
        try:
            preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
        except Exception:
            preflight = {}

    sidecar_cmd = [
        python_exe,
        str(root / "tools" / "sidecar_contract_validate.py"),
        "--dataroot",
        str(args.dataroot),
        "--max-journal-lines",
        str(int(args.max_journal_lines)),
    ]
    side_rc, side_payload, side_stdout = _run_json(sidecar_cmd, cwd=root)
    checks = side_payload.get("checks", {}) if isinstance(side_payload, dict) else {}
    activity = checks.get("activity_signal", {}) if isinstance(checks.get("activity_signal"), dict) else {}
    journal = checks.get("journal", {}) if isinstance(checks.get("journal"), dict) else {}
    ledger = checks.get("ledger", {}) if isinstance(checks.get("ledger"), dict) else {}
    media = checks.get("media", {}) if isinstance(checks.get("media"), dict) else {}
    metadata_db = checks.get("metadata_db", {}) if isinstance(checks.get("metadata_db"), dict) else {}
    media_count = int(media.get("files_count_sampled", 0) or 0)
    journal_mode_ok = bool(journal.get("ok", False)) and bool(ledger.get("present", False))
    metadata_mode_ok = bool(metadata_db.get("ok", False)) and bool(metadata_db.get("has_minimum_record_types", False))
    sidecar_min_ok = bool(media_count > 0 and bool(activity.get("present", False)) and (journal_mode_ok or metadata_mode_ok))

    ready = bool(preflight.get("ready", False))
    vllm_ok = ready
    overall_ok = bool(vllm_ok and sidecar_min_ok)

    payload = {
        "schema_version": 1,
        "ts_utc": _utc_now(),
        "ok": bool(overall_ok),
        "dataroot": str(args.dataroot),
        "vllm_base_url": str(args.vllm_base_url),
        "preflight": {
            "ok": bool(pre_rc == 0 and ready),
            "rc": int(pre_rc),
            "path": str(preflight_path),
            "stdout": pre_stdout,
        },
        "sidecar_contract": {
            "ok": bool(sidecar_min_ok),
            "rc": int(side_rc),
            "activity_signal_present": bool(activity.get("present", False)),
            "journal_ok": bool(journal.get("ok", False)),
            "ledger_present": bool(ledger.get("present", False)),
            "metadata_mode_ok": bool(metadata_mode_ok),
            "media_files_count_sampled": int(media.get("files_count_sampled", 0) or 0),
            "stdout": side_stdout,
        },
        "ready_breakdown": {
            "vllm_ready": bool(vllm_ok),
            "sidecar_min_ok": bool(sidecar_min_ok),
        },
    }

    out = Path(str(args.output))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": bool(overall_ok), "output": str(out)}, sort_keys=True))
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
