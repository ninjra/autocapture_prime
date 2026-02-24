#!/usr/bin/env python3
"""One-shot query pipeline triage snapshot."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.storage.stage1_derived_store import default_stage1_derived_db_path


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_stage1_audit_module() -> Any:
    mod_path = Path("tools/soak/stage1_completeness_audit.py").resolve()
    spec = importlib.util.spec_from_file_location("stage1_completeness_audit_for_triage", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable_to_load_stage1_completeness_audit_module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_gate_queryability_module() -> Any:
    mod_path = Path("tools/gate_queryability.py").resolve()
    spec = importlib.util.spec_from_file_location("gate_queryability_for_triage", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable_to_load_gate_queryability_module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _release_gate_popup_status(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    steps = payload.get("steps", []) if isinstance(payload.get("steps", []), list) else []
    out: dict[str, Any] = {
        "ok": bool(payload.get("ok", False)),
        "popup_go_no_go_ok": None,
        "gate_queryability_ok": None,
        "failed_step": str(payload.get("failed_step") or ""),
    }
    for row in steps:
        if not isinstance(row, dict):
            continue
        step_id = str(row.get("id") or "")
        if step_id == "popup_go_no_go":
            out["popup_go_no_go_ok"] = bool(row.get("ok", False))
        elif step_id == "gate_queryability":
            out["gate_queryability_ok"] = bool(row.get("ok", False))
    return out


def _run_stage1_audit(
    *,
    db: Path,
    derived_db: Path | None,
    gap_seconds: int,
    sample_limit: int,
    frame_limit: int,
    timeout_s: float,
) -> dict[str, Any]:
    module = _load_stage1_audit_module()
    resolved_db, resolved_reason = module._resolve_db_path(db)  # noqa: SLF001
    if not resolved_db.exists():
        return {
            "ok": False,
            "error": "db_not_found",
            "db_requested": str(db),
            "db_resolved": str(resolved_db),
            "db_resolution": str(resolved_reason),
        }
    resolved_derived = derived_db
    if resolved_derived is None:
        candidate = default_stage1_derived_db_path(resolved_db.parent)
        if candidate.exists():
            resolved_derived = candidate
    cmd = [
        str(sys.executable),
        "tools/soak/stage1_completeness_audit.py",
        "--db",
        str(resolved_db),
        "--gap-seconds",
        str(int(gap_seconds)),
        "--samples",
        str(int(sample_limit)),
        "--frame-limit",
        str(int(frame_limit)),
    ]
    if isinstance(resolved_derived, Path):
        cmd.extend(["--derived-db", str(resolved_derived)])
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True,
            text=True,
            check=False,
            timeout=max(1.0, float(timeout_s)),
        )
    except subprocess.TimeoutExpired:
        try:
            gate_mod = _load_gate_queryability_module()
            fast = gate_mod._fast_queryability_summary(resolved_db)  # noqa: SLF001
            if isinstance(fast, dict):
                fast["warning"] = "stage1_audit_timeout"
                fast["db_requested"] = str(db)
                fast["db_resolved"] = str(resolved_db)
                fast["db_resolution"] = str(resolved_reason)
                fast["derived_db_resolved"] = str(resolved_derived) if isinstance(resolved_derived, Path) else ""
                return fast
        except Exception:
            pass
        return {
            "ok": False,
            "error": "stage1_audit_timeout",
            "db_requested": str(db),
            "db_resolved": str(resolved_db),
            "db_resolution": str(resolved_reason),
            "derived_db_resolved": str(resolved_derived) if isinstance(resolved_derived, Path) else "",
        }
    payload: dict[str, Any] = {}
    stdout = str(proc.stdout or "").strip()
    if stdout:
        try:
            candidate = json.loads(stdout)
            if isinstance(candidate, dict):
                payload = candidate
        except Exception:
            payload = {}
    if not payload:
        payload = {
            "ok": False,
            "error": f"stage1_audit_invalid_output:rc={int(proc.returncode)}",
            "stdout_tail": stdout[-800:],
            "stderr_tail": str(proc.stderr or "")[-800:],
        }
    payload["db_requested"] = str(db)
    payload["db_resolved"] = str(resolved_db)
    payload["db_resolution"] = str(resolved_reason)
    payload["derived_db_resolved"] = str(resolved_derived) if isinstance(resolved_derived, Path) else ""
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-shot query pipeline triage report.")
    parser.add_argument("--db", default="/mnt/d/autocapture/metadata.db")
    parser.add_argument("--derived-db", default="")
    parser.add_argument("--gap-seconds", type=int, default=120)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--frame-limit", type=int, default=400)
    parser.add_argument("--stage1-timeout-s", type=float, default=10.0)
    parser.add_argument("--popup-go-no-go", default="artifacts/query_acceptance/popup_go_no_go_latest.json")
    parser.add_argument("--release-gate", default="artifacts/release/release_gate_latest.json")
    parser.add_argument("--out", default="artifacts/query_acceptance/query_pipeline_triage_latest.json")
    args = parser.parse_args(argv)

    db = Path(str(args.db)).expanduser()
    derived_db = Path(str(args.derived_db)).expanduser() if str(args.derived_db or "").strip() else None
    stage1 = _run_stage1_audit(
        db=db,
        derived_db=derived_db,
        gap_seconds=int(args.gap_seconds),
        sample_limit=int(args.sample_limit),
        frame_limit=int(args.frame_limit),
        timeout_s=float(args.stage1_timeout_s),
    )
    summary = stage1.get("summary", {}) if isinstance(stage1.get("summary", {}), dict) else {}
    popup = _load_json(Path(str(args.popup_go_no_go)).expanduser())
    popup_compact = popup.get("compact_summary", {}) if isinstance(popup.get("compact_summary", {}), dict) else {}
    release = _release_gate_popup_status(Path(str(args.release_gate)).expanduser())

    payload = {
        "schema_version": 1,
        "record_type": "derived.eval.query_pipeline_triage",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "stage1": {
            "ok": bool(stage1.get("ok", False)),
            "frames_total": _int(summary.get("frames_total", 0)),
            "frames_queryable": _int(summary.get("frames_queryable", 0)),
            "frames_blocked": _int(summary.get("frames_blocked", 0)),
            "contiguous_queryable_windows": _int(summary.get("contiguous_queryable_windows", 0)),
            "db_resolved": str(stage1.get("db_resolved") or ""),
            "derived_db_resolved": str(stage1.get("derived_db_resolved") or ""),
        },
        "popup_go_no_go": {
            "ok": bool(popup.get("ok", False)),
            "failed_count": _int(popup_compact.get("failed_count", 0)),
            "top_failure_class": str(popup_compact.get("top_failure_class") or ""),
            "top_failure_key": str(popup_compact.get("top_failure_key") or ""),
            "latency_p50_ms": float(popup_compact.get("latency_p50_ms", 0.0) or 0.0),
            "latency_p95_ms": float(popup_compact.get("latency_p95_ms", 0.0) or 0.0),
        },
        "release_gate": release,
    }
    out_path = Path(str(args.out)).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out_path.resolve())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
