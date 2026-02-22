#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.storage.stage1_derived_store import default_stage1_derived_db_path


def _load_audit_module() -> Any:
    mod_path = Path("tools/soak/stage1_completeness_audit.py").resolve()
    spec = importlib.util.spec_from_file_location("stage1_completeness_audit_module", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable_to_load_stage1_completeness_audit")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    summary = payload.get("summary", {}) if isinstance(payload.get("summary", {}), dict) else {}
    plugin_completion = payload.get("plugin_completion", {}) if isinstance(payload.get("plugin_completion", {}), dict) else {}
    rows = payload.get("frame_lineage", []) if isinstance(payload.get("frame_lineage", []), list) else []
    lines: list[str] = []
    lines.append("# Stage1->Stage2 Lineage Queryability Report")
    lines.append("")
    lines.append(f"- ts_utc: `{datetime.now(timezone.utc).isoformat()}`")
    lines.append(f"- db: `{payload.get('db_resolved') or payload.get('db') or ''}`")
    lines.append(f"- derived_db: `{payload.get('derived_db') or ''}`")
    lines.append(f"- frames_total: `{int(summary.get('frames_total', 0) or 0)}`")
    lines.append(f"- frames_queryable: `{int(summary.get('frames_queryable', 0) or 0)}`")
    lines.append(f"- frames_blocked: `{int(summary.get('frames_blocked', 0) or 0)}`")
    lines.append(f"- frame_lineage_total: `{int(payload.get('frame_lineage_total', 0) or 0)}`")
    lines.append(f"- frame_lineage_limit: `{int(payload.get('frame_lineage_limit', 0) or 0)}`")
    lines.append("")
    lines.append("## Plugin Completion")
    lines.append("")
    lines.append("| plugin | ok | required |")
    lines.append("|---|---:|---:|")
    for key in sorted(plugin_completion.keys()):
        row = plugin_completion.get(key, {}) if isinstance(plugin_completion.get(key, {}), dict) else {}
        lines.append(f"| {key} | {int(row.get('ok', 0) or 0)} | {int(row.get('required', 0) or 0)} |")
    lines.append("")
    lines.append("## Frame Lineage")
    lines.append("")
    lines.append("| frame_id | ts_utc | queryable | stage1 | retention | uia_snapshot | obs_focus | obs_context | obs_operable | issues |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for row in rows:
        if not isinstance(row, dict):
            continue
        plugins = row.get("plugins", {}) if isinstance(row.get("plugins", {}), dict) else {}
        issues = ", ".join([str(item) for item in (row.get("issues") or []) if str(item)]) or "-"
        def _ok(key: str) -> str:
            item = plugins.get(key, {}) if isinstance(plugins.get(key, {}), dict) else {}
            return "Y" if bool(item.get("ok", False)) else "N"
        lines.append(
            "| {frame} | {ts} | {queryable} | {stage1} | {retention} | {uia} | {focus} | {context} | {operable} | {issues} |".format(
                frame=str(row.get("frame_id") or ""),
                ts=str(row.get("ts_utc") or ""),
                queryable="Y" if bool(row.get("queryable", False)) else "N",
                stage1=_ok("stage1_complete"),
                retention=_ok("retention_eligible"),
                uia=_ok("uia_snapshot"),
                focus=_ok("obs_uia_focus"),
                context=_ok("obs_uia_context"),
                operable=_ok("obs_uia_operable"),
                issues=issues,
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Stage1->Stage2 lineage/queryability report.")
    parser.add_argument("--db", default="/mnt/d/autocapture/metadata.db")
    parser.add_argument("--derived-db", default="")
    parser.add_argument("--gap-seconds", type=int, default=120)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--frame-limit", type=int, default=400)
    parser.add_argument("--out-json", default="")
    parser.add_argument("--out-md", default="")
    args = parser.parse_args()

    module = _load_audit_module()
    requested_db = Path(str(args.db)).expanduser()
    resolved_db, resolved_reason = module._resolve_db_path(requested_db)  # noqa: SLF001
    if not resolved_db.exists():
        print(json.dumps({"ok": False, "error": "db_not_found", "db": str(resolved_db)}, sort_keys=True))
        return 2
    raw_derived = str(args.derived_db or "").strip()
    derived_db: Path | None = Path(raw_derived).expanduser() if raw_derived else None
    if derived_db is None:
        candidate = default_stage1_derived_db_path(resolved_db.parent)
        if candidate.exists():
            derived_db = candidate
    try:
        payload = module.run_audit(  # noqa: SLF001
            resolved_db,
            derived_db_path=derived_db,
            gap_seconds=int(args.gap_seconds),
            sample_limit=int(args.samples),
            frame_report_limit=int(args.frame_limit),
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}:{exc}"}, sort_keys=True))
        return 1

    payload["db_requested"] = str(requested_db)
    payload["db_resolved"] = str(resolved_db)
    payload["db_resolution"] = str(resolved_reason)
    out_dir = Path("artifacts/lineage") / _utc_stamp()
    out_json = Path(str(args.out_json).strip()) if str(args.out_json).strip() else out_dir / "stage1_stage2_lineage_queryability.json"
    out_md = Path(str(args.out_md).strip()) if str(args.out_md).strip() else out_dir / "stage1_stage2_lineage_queryability.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_markdown(out_md, payload)
    print(
        json.dumps(
            {
                "ok": bool(payload.get("ok", False)),
                "out_json": str(out_json.resolve()),
                "out_md": str(out_md.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0 if bool(payload.get("ok", False)) else 3


if __name__ == "__main__":
    raise SystemExit(main())
