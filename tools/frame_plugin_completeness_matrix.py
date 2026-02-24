#!/usr/bin/env python3
"""Emit per-frame plugin completeness matrix from Stage1 audit data."""

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
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected_json_object:{path}")
    return payload


def _load_stage1_audit_module() -> Any:
    mod_path = Path("tools/soak/stage1_completeness_audit.py").resolve()
    spec = importlib.util.spec_from_file_location("stage1_completeness_audit_for_matrix", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable_to_load_stage1_completeness_audit_module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plugin_ok(plugins: dict[str, Any], plugin_id: str) -> bool:
    row = plugins.get(plugin_id, {}) if isinstance(plugins.get(plugin_id, {}), dict) else {}
    return bool(row.get("ok", False))


def _required_plugins(plugins: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key, value in plugins.items():
        if not isinstance(value, dict):
            continue
        if bool(value.get("required", False)):
            out.append(str(key))
    return sorted(out)


def build_matrix(audit: dict[str, Any]) -> dict[str, Any]:
    frame_rows = audit.get("frame_lineage", []) if isinstance(audit.get("frame_lineage", []), list) else []
    rows: list[dict[str, Any]] = []
    for frame in frame_rows:
        if not isinstance(frame, dict):
            continue
        plugins = frame.get("plugins", {}) if isinstance(frame.get("plugins", {}), dict) else {}
        required = _required_plugins(plugins)
        missing = [plugin_id for plugin_id in required if not _plugin_ok(plugins, plugin_id)]
        rows.append(
            {
                "frame_id": str(frame.get("frame_id") or ""),
                "ts_utc": str(frame.get("ts_utc") or ""),
                "queryable": bool(frame.get("queryable", False)),
                "required_plugins": required,
                "missing_plugins": missing,
                "issue_count": int(len([x for x in (frame.get("issues") or []) if str(x)])),
                "issues": [str(x) for x in (frame.get("issues") or []) if str(x)],
                "plugins": plugins,
            }
        )
    frames_total = len(rows)
    frames_complete = sum(1 for row in rows if len(row.get("missing_plugins", [])) == 0)
    frames_incomplete = max(0, frames_total - frames_complete)
    missing_counts: dict[str, int] = {}
    for row in rows:
        for plugin_id in row.get("missing_plugins", []):
            key = str(plugin_id)
            missing_counts[key] = int(missing_counts.get(key, 0) + 1)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "frames_total": int(frames_total),
        "frames_complete": int(frames_complete),
        "frames_incomplete": int(frames_incomplete),
        "missing_plugin_counts": dict(sorted(missing_counts.items())),
        "rows": rows,
    }


def _write_markdown(path: Path, matrix: dict[str, Any]) -> None:
    rows = matrix.get("rows", []) if isinstance(matrix.get("rows", []), list) else []
    lines: list[str] = []
    lines.append("# Frame Plugin Completeness Matrix")
    lines.append("")
    lines.append(f"- generated_at_utc: `{matrix.get('generated_at_utc')}`")
    lines.append(f"- frames_total: `{int(matrix.get('frames_total', 0) or 0)}`")
    lines.append(f"- frames_complete: `{int(matrix.get('frames_complete', 0) or 0)}`")
    lines.append(f"- frames_incomplete: `{int(matrix.get('frames_incomplete', 0) or 0)}`")
    lines.append("")
    lines.append("## Missing Plugin Counts")
    lines.append("")
    lines.append("| plugin_id | missing_count |")
    lines.append("|---|---:|")
    for plugin_id, count in (matrix.get("missing_plugin_counts", {}) or {}).items():
        lines.append(f"| {plugin_id} | {int(count)} |")
    lines.append("")
    lines.append("## Frame Rows")
    lines.append("")
    lines.append("| frame_id | ts_utc | queryable | missing_plugins | issues |")
    lines.append("|---|---|---:|---|---|")
    for row in rows:
        if not isinstance(row, dict):
            continue
        missing = ", ".join(str(x) for x in (row.get("missing_plugins") or []) if str(x)) or "-"
        issues = ", ".join(str(x) for x in (row.get("issues") or []) if str(x)) or "-"
        lines.append(
            "| {frame_id} | {ts_utc} | {queryable} | {missing} | {issues} |".format(
                frame_id=str(row.get("frame_id") or ""),
                ts_utc=str(row.get("ts_utc") or ""),
                queryable="true" if bool(row.get("queryable", False)) else "false",
                missing=missing,
                issues=issues,
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_stage1_audit_subprocess(
    *,
    db: Path,
    derived_db: Path | None,
    gap_seconds: int,
    sample_limit: int,
    frame_limit: int,
    timeout_s: float,
) -> tuple[dict[str, Any], str]:
    cmd = [
        str(sys.executable),
        "tools/soak/stage1_completeness_audit.py",
        "--db",
        str(db),
        "--gap-seconds",
        str(int(gap_seconds)),
        "--samples",
        str(int(sample_limit)),
        "--frame-limit",
        str(int(frame_limit)),
    ]
    if isinstance(derived_db, Path):
        cmd.extend(["--derived-db", str(derived_db)])
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
        return (
            {
                "ok": False,
                "error": "stage1_audit_timeout",
                "frame_lineage": [],
            },
            "stage1_audit_timeout",
        )
    stdout = str(proc.stdout or "").strip()
    if not stdout:
        return (
            {"ok": False, "error": f"stage1_audit_empty_output:rc={int(proc.returncode)}", "frame_lineage": []},
            "stage1_audit_empty_output",
        )
    try:
        payload = json.loads(stdout)
    except Exception:
        payload = {}
    if not isinstance(payload, dict) or not payload:
        return (
            {"ok": False, "error": f"stage1_audit_invalid_output:rc={int(proc.returncode)}", "frame_lineage": []},
            "stage1_audit_invalid_output",
        )
    return payload, ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build per-frame plugin completeness matrix.")
    parser.add_argument("--audit-report", default="", help="Optional existing stage1 audit report JSON path.")
    parser.add_argument("--db", default="/mnt/d/autocapture/metadata.db")
    parser.add_argument("--derived-db", default="")
    parser.add_argument("--gap-seconds", type=int, default=120)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--frame-limit", type=int, default=400)
    parser.add_argument("--audit-timeout-s", type=float, default=10.0)
    parser.add_argument("--out-json", default="artifacts/lineage/frame_plugin_completeness_matrix.json")
    parser.add_argument("--out-md", default="artifacts/lineage/frame_plugin_completeness_matrix.md")
    args = parser.parse_args(argv)

    audit_report = Path(str(args.audit_report).strip()) if str(args.audit_report).strip() else None
    if isinstance(audit_report, Path):
        audit = _load_json(audit_report)
    else:
        module = _load_stage1_audit_module()
        requested_db = Path(str(args.db)).expanduser()
        resolved_db, _resolved_reason = module._resolve_db_path(requested_db)  # noqa: SLF001
        if not resolved_db.exists():
            print(json.dumps({"ok": False, "error": "db_not_found", "db": str(resolved_db)}, sort_keys=True))
            return 2
        derived_db: Path | None = None
        if str(args.derived_db or "").strip():
            derived_db = Path(str(args.derived_db)).expanduser()
        else:
            candidate = default_stage1_derived_db_path(resolved_db.parent)
            if candidate.exists():
                derived_db = candidate
        audit, audit_err = _run_stage1_audit_subprocess(
            db=resolved_db,
            derived_db=derived_db,
            gap_seconds=int(args.gap_seconds),
            sample_limit=int(args.sample_limit),
            frame_limit=int(args.frame_limit),
            timeout_s=float(args.audit_timeout_s),
        )
        if audit_err:
            matrix = {
                "schema_version": 1,
                "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "frames_total": 0,
                "frames_complete": 0,
                "frames_incomplete": 0,
                "missing_plugin_counts": {},
                "rows": [],
                "error": str(audit_err),
            }
            out_json = Path(str(args.out_json)).expanduser()
            out_md = Path(str(args.out_md)).expanduser()
            out_json.parent.mkdir(parents=True, exist_ok=True)
            out_json.write_text(json.dumps(matrix, indent=2, sort_keys=True), encoding="utf-8")
            _write_markdown(out_md, matrix)
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": str(audit_err),
                        "out_json": str(out_json.resolve()),
                        "out_md": str(out_md.resolve()),
                    },
                    sort_keys=True,
                )
            )
            return 1

    matrix = build_matrix(audit)
    out_json = Path(str(args.out_json)).expanduser()
    out_md = Path(str(args.out_md)).expanduser()
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(matrix, indent=2, sort_keys=True), encoding="utf-8")
    _write_markdown(out_md, matrix)
    print(
        json.dumps(
            {
                "ok": True,
                "out_json": str(out_json.resolve()),
                "out_md": str(out_md.resolve()),
                "frames_total": int(matrix.get("frames_total", 0) or 0),
                "frames_incomplete": int(matrix.get("frames_incomplete", 0) or 0),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
