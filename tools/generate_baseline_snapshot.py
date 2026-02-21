#!/usr/bin/env python3
"""Build deterministic baseline snapshot from core release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


VOLATILE_KEYS = {
    "ts_utc",
    "started_utc",
    "finished_utc",
    "created_utc",
    "stopped_at",
    "pid",
    "elapsed_ms",
    "elapsed_s",
    "run_id",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _git_head(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        head = str(proc.stdout or "").strip()
        if proc.returncode == 0 and head:
            return head
    except Exception:
        pass
    return ""


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key in sorted(value.keys(), key=lambda x: str(x)):
            key_s = str(key)
            if key_s in VOLATILE_KEYS:
                continue
            out[key_s] = _normalize(value[key])
        return out
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, float):
        return float(round(value, 6))
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def build_snapshot(inputs: list[Path], *, root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for path in inputs:
        rel = str(path if path.is_absolute() else path)
        full = path if path.is_absolute() else (root / path)
        if not full.exists():
            missing.append(rel)
            continue
        try:
            payload = json.loads(full.read_text(encoding="utf-8"))
        except Exception:
            missing.append(rel)
            continue
        normalized = _normalize(payload)
        rows.append({"path": rel, "normalized": normalized})
    rows_sorted = sorted(rows, key=lambda item: str(item.get("path") or ""))
    canonical = _canonical_json(rows_sorted)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "schema_version": 1,
        "git_head": _git_head(root),
        "inputs": [str(p) for p in inputs],
        "missing": sorted(set(missing)),
        "rows": rows_sorted,
        "summary": {
            "present_count": len(rows_sorted),
            "missing_count": len(sorted(set(missing))),
            "normalized_sha256": digest,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="Relative/absolute JSON artifact path. Repeatable.",
    )
    parser.add_argument("--output", default="artifacts/baseline/baseline_snapshot_latest.json")
    args = parser.parse_args(argv)

    root = _repo_root()
    defaults = [
        Path("artifacts/live_stack/preflight_latest.json"),
        Path("artifacts/live_stack/validation_latest.json"),
        Path("artifacts/release/release_gate_latest.json"),
        Path("artifacts/perf/gate_perf.json"),
        Path("artifacts/perf/gate_promptops_perf.json"),
    ]
    inputs = [Path(str(item)) for item in (list(args.input) if args.input else defaults)]
    payload = build_snapshot(inputs, root=root)
    out = root / str(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": payload.get("summary", {}).get("present_count", 0) > 0,
                "output": str(out),
                "normalized_sha256": payload.get("summary", {}).get("normalized_sha256", ""),
                "missing_count": payload.get("summary", {}).get("missing_count", 0),
            },
            sort_keys=True,
        )
    )
    return 0 if int(payload.get("summary", {}).get("present_count", 0) or 0) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

