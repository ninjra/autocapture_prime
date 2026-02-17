#!/usr/bin/env python3
"""Soak admission checks for the golden pipeline."""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_advanced(path_glob: str) -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    pattern = str(path_glob or "").strip()
    if not pattern:
        return []
    if Path(pattern).is_absolute():
        raw = [Path(p) for p in glob.glob(pattern)]
    else:
        raw = [Path(p) for p in glob.glob(str(root / pattern))]
    paths = [p for p in raw if p.exists() and p.is_file()]
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


def _advanced_ok(payload: dict[str, Any]) -> bool:
    total = int(payload.get("evaluated_total", 0) or 0)
    passed = int(payload.get("evaluated_passed", 0) or 0)
    failed = int(payload.get("evaluated_failed", 0) or 0)
    return total >= 20 and passed == total and failed == 0


def _citation_success_ratio(payload: dict[str, Any]) -> float:
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) == 0:
        return 0.0
    with_citations = 0
    for row in rows:
        providers = row.get("providers") if isinstance(row, dict) else None
        citation_total = 0
        if isinstance(providers, list):
            for provider in providers:
                if isinstance(provider, dict):
                    citation_total += int(provider.get("citation_count", 0) or 0)
        if citation_total > 0:
            with_citations += 1
    return float(with_citations) / float(len(rows))


def _precheck(
    *,
    release_report: Path,
    advanced_glob: str,
    require_runs: int,
    citation_min_ratio: float,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    release_ok = False
    if release_report.exists():
        release_payload = _load_json(release_report)
        release_ok = bool(release_payload.get("ok", False))
    checks.append({"name": "release_gate_ok", "ok": release_ok, "path": str(release_report)})

    selected_paths = _collect_advanced(advanced_glob)
    selected = selected_paths[: max(0, require_runs)]
    runs: list[dict[str, Any]] = []
    all_runs_pass = len(selected) == require_runs and require_runs > 0
    for path in selected:
        payload = _load_json(path)
        run_ok = _advanced_ok(payload)
        citation_ratio = _citation_success_ratio(payload)
        if citation_ratio < citation_min_ratio:
            run_ok = False
        runs.append(
            {
                "path": str(path),
                "ok": run_ok,
                "evaluated_total": int(payload.get("evaluated_total", 0) or 0),
                "evaluated_passed": int(payload.get("evaluated_passed", 0) or 0),
                "evaluated_failed": int(payload.get("evaluated_failed", 0) or 0),
                "citation_ratio": citation_ratio,
            }
        )
        if not run_ok:
            all_runs_pass = False
    checks.append(
        {
            "name": "advanced_runs",
            "ok": all_runs_pass,
            "require_runs": require_runs,
            "found_runs": len(selected),
            "citation_min_ratio": citation_min_ratio,
        }
    )
    ok = all(bool(c.get("ok", False)) for c in checks)
    return {"ok": ok, "mode": "pre", "checks": checks, "runs": runs}


def _postcheck(
    *,
    soak_summary: Path,
    min_elapsed_s: int,
    max_failed_attempts: int,
    max_blocked_vllm: int,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    payload: dict[str, Any] = {}
    summary_exists = soak_summary.exists()
    if summary_exists:
        payload = _load_json(soak_summary)
    checks.append({"name": "summary_exists", "ok": summary_exists, "path": str(soak_summary)})
    elapsed = int(payload.get("elapsed_s", 0) or 0)
    failed = int(payload.get("failed", 0) or 0)
    blocked = int(payload.get("blocked_vllm", 0) or 0)
    checks.append({"name": "elapsed_min", "ok": elapsed >= min_elapsed_s, "value": elapsed, "min": min_elapsed_s})
    checks.append(
        {"name": "failed_attempts_max", "ok": failed <= max_failed_attempts, "value": failed, "max": max_failed_attempts}
    )
    checks.append({"name": "blocked_vllm_max", "ok": blocked <= max_blocked_vllm, "value": blocked, "max": max_blocked_vllm})
    checks.append({"name": "summary_ok_field", "ok": bool(payload.get("ok", False))})
    ok = all(bool(c.get("ok", False)) for c in checks)
    return {"ok": ok, "mode": "post", "checks": checks, "summary": payload}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Golden soak admission checks")
    parser.add_argument("--mode", choices=("pre", "post"), default="pre")
    parser.add_argument("--release-report", default="artifacts/release/release_gate_latest.json")
    parser.add_argument("--advanced-glob", default="artifacts/advanced10/advanced20_*.json")
    parser.add_argument("--require-runs", type=int, default=3)
    parser.add_argument("--citation-min-ratio", type=float, default=0.9)
    parser.add_argument("--soak-summary", default="artifacts/soak/golden_qh/latest/summary.json")
    parser.add_argument("--min-elapsed-s", type=int, default=86400)
    parser.add_argument("--max-failed-attempts", type=int, default=0)
    parser.add_argument("--max-blocked-vllm", type=int, default=0)
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[2]
    if args.mode == "pre":
        payload = _precheck(
            release_report=(root / args.release_report),
            advanced_glob=args.advanced_glob,
            require_runs=max(1, int(args.require_runs)),
            citation_min_ratio=float(args.citation_min_ratio),
        )
    else:
        payload = _postcheck(
            soak_summary=(root / args.soak_summary),
            min_elapsed_s=max(1, int(args.min_elapsed_s)),
            max_failed_attempts=max(0, int(args.max_failed_attempts)),
            max_blocked_vllm=max(0, int(args.max_blocked_vllm)),
        )

    out_arg = str(args.output or "").strip()
    if out_arg:
        out = root / out_arg
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0 if bool(payload.get("ok", False)) else 2


if __name__ == "__main__":
    raise SystemExit(main())
