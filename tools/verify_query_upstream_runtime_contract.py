#!/usr/bin/env python3
"""Verify 8788 upstream runtime env contract used by popup query."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _read_environ(path: Path) -> dict[str, str]:
    try:
        raw = path.read_bytes()
    except Exception:
        return {}
    out: dict[str, str] = {}
    for chunk in raw.split(b"\x00"):
        if not chunk:
            continue
        text = chunk.decode("utf-8", errors="ignore")
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        out[str(key)] = str(value)
    return out


def _find_upstream_pid(port: int) -> int | None:
    target_1 = "autocapture_query_upstream_server.py"
    target_2 = f"--port {int(port)}"
    best: int | None = None
    proc_root = Path("/proc")
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        cmdline = _read_text(entry / "cmdline").replace("\x00", " ").strip()
        if target_1 not in cmdline:
            continue
        if target_2 not in cmdline:
            continue
        if best is None or pid > best:
            best = pid
    return best


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate popup upstream runtime env contract.")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--expected-config-dir", default="/mnt/d/autocapture/config_wsl")
    parser.add_argument("--expected-source-prefix", default="/tmp/autocapture_query_upstream_data_8788")
    parser.add_argument("--expected-metadata-only", default="1")
    parser.add_argument("--output", default="artifacts/query_acceptance/upstream_runtime_contract_latest.json")
    args = parser.parse_args(argv)

    reasons: list[str] = []
    pid = _find_upstream_pid(int(args.port))
    env: dict[str, str] = {}
    if pid is None:
        reasons.append("upstream_pid_not_found")
    else:
        env = _read_environ(Path("/proc") / str(pid) / "environ")
        got_config = str(env.get("AUTOCAPTURE_CONFIG_DIR") or "")
        got_data = str(env.get("AUTOCAPTURE_DATA_DIR") or "")
        got_metadata_only = str(env.get("AUTOCAPTURE_QUERY_METADATA_ONLY") or "")
        if got_config != str(args.expected_config_dir):
            reasons.append("config_dir_mismatch")
        if not got_data.startswith(str(args.expected_source_prefix)):
            reasons.append("data_dir_prefix_mismatch")
        if got_metadata_only != str(args.expected_metadata_only):
            reasons.append("metadata_only_mismatch")

    out = {
        "schema_version": 1,
        "ok": len(reasons) == 0,
        "port": int(args.port),
        "pid": pid,
        "expected": {
            "config_dir": str(args.expected_config_dir),
            "data_dir_prefix": str(args.expected_source_prefix),
            "metadata_only": str(args.expected_metadata_only),
        },
        "observed": {
            "AUTOCAPTURE_CONFIG_DIR": str(env.get("AUTOCAPTURE_CONFIG_DIR") or ""),
            "AUTOCAPTURE_DATA_DIR": str(env.get("AUTOCAPTURE_DATA_DIR") or ""),
            "AUTOCAPTURE_QUERY_METADATA_ONLY": str(env.get("AUTOCAPTURE_QUERY_METADATA_ONLY") or ""),
        },
        "failure_reasons": reasons,
    }
    out_path = Path(str(args.output))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": out["ok"], "output": str(out_path.resolve())}, sort_keys=True))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

