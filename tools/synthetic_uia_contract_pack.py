#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ANCHOR_TEXTS: tuple[str, ...] = (
    "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476",
    "Permian Resources Service Desk",
    "permian.xyz.com",
    "Your record was updated on Feb 02, 2026 - 12:08pm CST",
    "Mary Mata created the incident on Feb 02, 2026 - 12:08pm CST",
    "State changed from New to Assigned",
    "For videos, ping you in 5 - 10 mins?",
    "gwatt",
    "Summary column derived from payload fields",
    "src/statistic_harness/v4/templates/vectors.html",
    "src/statistic_harness/v4/server.py",
    "PYTHONPATH=src /tmp/stat_harness_venv/bin/python -m pytest -q",
    "Write-Host \"Using WSL IP endpoint $saltEndpoint for $projectId\" -ForegroundColor Yellow",
    "statistic_harness",
    "chatgpt.com",
    "listen.siriusxm.com",
    "Remote Desktop Web Client",
    "SiriusXM",
    "Slack",
    "ChatGPT",
    "8",
    "16",
    "Yes",
    "white dialog/window",
    "blue background",
)

_SECTION_ANCHORS: dict[str, tuple[str, ...]] = {
    "focus": (
        "Slack",
        "ChatGPT",
        "Remote Desktop Web Client",
        "SiriusXM",
        "Permian Resources Service Desk",
        "Task Set Up Open Invoice for Contractor Ricardo Lopez for Incident #58476",
        "COMPLETE",
        "VIEW DETAILS",
        "Yes",
    ),
    "context": (
        "Summary column derived from payload fields",
        "src/statistic_harness/v4/templates/vectors.html",
        "src/statistic_harness/v4/server.py",
        "PYTHONPATH=src /tmp/stat_harness_venv/bin/python -m pytest -q",
        "Write-Host \"Using WSL IP endpoint $saltEndpoint for $projectId\" -ForegroundColor Yellow",
        "k presets: 32, 64, 128",
        "clamp range inclusive: [1, 200]",
        "For videos, ping you in 5 - 10 mins?",
        "gwatt",
        "[x] Implement vector store pagination",
        "[x] Execute tests and verify report",
        "[x] Improve docs readability",
        "[x] Remove stale assumptions",
        "[x] Validate strict matrix output",
        "Running test coverage mapping (in 3s - esc to interrupt)",
        "January 2026",
        "Selected date: Feb 02, 2026",
        "12:00pm - Assigned task review",
        "12:08pm - Incident update",
        "12:10pm - State changed to Assigned",
    ),
    "operable": (
        "COMPLETE",
        "VIEW DETAILS",
    ),
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _build_nodes(section: str, count: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    base_role = {"focus": "Edit", "context": "ListItem", "operable": "Button"}[section]
    section_anchors = _SECTION_ANCHORS.get(section, ())
    for idx in range(max(0, int(count))):
        left = 10 + (idx * 17)
        top = 20 + (idx * 13)
        right = left + 140
        bottom = top + 36
        anchor = ""
        if idx < len(section_anchors):
            anchor = str(section_anchors[idx])
        elif _ANCHOR_TEXTS:
            anchor = _ANCHOR_TEXTS[idx % len(_ANCHOR_TEXTS)]
        if section == "operable" and idx == 0:
            left, top, right, bottom = 1534, 191, 1583, 204
        elif section == "operable" and idx == 1:
            left, top, right, bottom = 1587, 191, 1637, 204
        node: dict[str, Any] = {
            "eid": f"{section}-{idx}",
            "role": base_role,
            "name": f"{section.title()} Node {idx}: {anchor}" if anchor else f"{section.title()} Node {idx}",
            "aid": f"{section}.aid.{idx}",
            "class": f"{base_role}Class",
            "rect": [left, top, right, bottom],
            "enabled": True,
            "offscreen": False,
        }
        if section == "operable":
            node["hot"] = bool(idx == 0)
        out.append(node)
    return out


def build_snapshot(
    *,
    record_id: str,
    run_id: str,
    ts_utc: str,
    hwnd: str,
    window_title: str,
    process_path: str,
    pid: int,
    focus_nodes: int,
    context_nodes: int,
    operable_nodes: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "record_type": "evidence.uia.snapshot",
        "record_id": str(record_id),
        "run_id": str(run_id),
        "ts_utc": str(ts_utc),
        "unix_ms_utc": int(datetime.fromisoformat(str(ts_utc).replace("Z", "+00:00")).timestamp() * 1000),
        "hwnd": str(hwnd),
        "window": {
            "title": str(window_title),
            "process_path": str(process_path),
            "pid": int(pid),
        },
        "focus_path": _build_nodes("focus", focus_nodes),
        "context_peers": _build_nodes("context", context_nodes),
        "operables": _build_nodes("operable", operable_nodes),
        "stats": {
            "walk_ms": 12,
            "nodes_emitted": int(max(0, focus_nodes) + max(0, context_nodes) + max(0, operable_nodes)),
            "failures": 0,
        },
    }
    payload["content_hash"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return payload


def build_contract_pack(
    *,
    run_id: str,
    uia_record_id: str,
    ts_utc: str,
    hash_mode: str,
    focus_nodes: int,
    context_nodes: int,
    operable_nodes: int,
) -> dict[str, Any]:
    snapshot = build_snapshot(
        record_id=uia_record_id,
        run_id=run_id,
        ts_utc=ts_utc,
        hwnd="0x001A01",
        window_title="Remote Desktop Web Client | Slack | ChatGPT | SiriusXM | Permian Resources Service Desk",
        process_path="C:\\Synthetic\\App.exe",
        pid=4242,
        focus_nodes=focus_nodes,
        context_nodes=context_nodes,
        operable_nodes=operable_nodes,
    )
    ref_hash = str(snapshot.get("content_hash") or "")
    if str(hash_mode) == "mismatch":
        ref_hash = "0" * 64
    return {
        "run_id": str(run_id),
        "uia_ref": {
            "record_id": str(uia_record_id),
            "ts_utc": str(ts_utc),
            "content_hash": ref_hash,
        },
        "metadata_record": {
            "record_id": str(uia_record_id),
            "record_type": "evidence.uia.snapshot",
            "payload": snapshot,
            "content_hash": str(snapshot.get("content_hash") or ""),
        },
        "snapshot": snapshot,
    }


def write_contract_pack(
    *,
    out_dir: Path,
    run_id: str,
    uia_record_id: str,
    ts_utc: str,
    hash_mode: str,
    focus_nodes: int,
    context_nodes: int,
    operable_nodes: int,
    write_hash_file: bool,
) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pack = build_contract_pack(
        run_id=run_id,
        uia_record_id=uia_record_id,
        ts_utc=ts_utc,
        hash_mode=hash_mode,
        focus_nodes=focus_nodes,
        context_nodes=context_nodes,
        operable_nodes=operable_nodes,
    )
    snapshot = dict(pack["snapshot"])
    uia_dir = out / "uia"
    uia_dir.mkdir(parents=True, exist_ok=True)
    latest_snap = uia_dir / "latest.snap.json"
    snap_bytes = _canonical_bytes(snapshot)
    latest_snap.write_bytes(snap_bytes)
    latest_hash = hashlib.sha256(snap_bytes).hexdigest()

    hash_path = uia_dir / "latest.snap.sha256"
    if write_hash_file:
        hash_value = latest_hash if str(hash_mode) == "match" else ("f" * 64)
        hash_path.write_text(f"{hash_value}  latest.snap.json\n", encoding="utf-8")

    pack_path = out / "synthetic_uia_contract_pack.json"
    output: dict[str, Any] = dict(pack)
    output["fallback"] = {
        "latest_snap_json": str(latest_snap),
        "latest_snap_sha256": str(hash_path) if write_hash_file else "",
        "latest_snap_file_hash": latest_hash,
    }
    pack_path.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "ok": True,
        "pack_path": str(pack_path),
        "fallback_latest_snap": str(latest_snap),
        "fallback_latest_hash": str(hash_path) if write_hash_file else "",
        "hash_mode": str(hash_mode),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build synthetic Hypervisor UIA contract fixtures.")
    parser.add_argument("--out-dir", required=True, help="Output directory for generated synthetic UIA files.")
    parser.add_argument("--run-id", default="run_synthetic_uia")
    parser.add_argument("--uia-record-id", default="")
    parser.add_argument("--ts-utc", default="")
    parser.add_argument("--hash-mode", choices=("match", "mismatch"), default="match")
    parser.add_argument("--focus-nodes", type=int, default=3)
    parser.add_argument("--context-nodes", type=int, default=5)
    parser.add_argument("--operable-nodes", type=int, default=7)
    parser.add_argument("--write-hash-file", action="store_true", default=True)
    parser.add_argument("--no-write-hash-file", dest="write_hash_file", action="store_false")
    args = parser.parse_args()

    ts_utc = str(args.ts_utc or "").strip() or _utc_now_iso()
    run_id = str(args.run_id or "run_synthetic_uia").strip()
    uia_record_id = str(args.uia_record_id or "").strip() or f"{run_id}/uia/0"
    result = write_contract_pack(
        out_dir=Path(args.out_dir),
        run_id=run_id,
        uia_record_id=uia_record_id,
        ts_utc=ts_utc,
        hash_mode=str(args.hash_mode),
        focus_nodes=int(args.focus_nodes),
        context_nodes=int(args.context_nodes),
        operable_nodes=int(args.operable_nodes),
        write_hash_file=bool(args.write_hash_file),
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
