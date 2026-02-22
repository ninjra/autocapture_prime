#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any


def _canonical_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _extract_last_json(output: str) -> dict[str, Any]:
    last: dict[str, Any] = {}
    for raw in str(output or "").splitlines():
        line = str(raw or "").strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            last = obj
    return last


def _matrix_signature(matrix: dict[str, Any]) -> str:
    core = {
        "ok": bool(matrix.get("ok", False)),
        "matrix_total": int(matrix.get("matrix_total", 0) or 0),
        "matrix_evaluated": int(matrix.get("matrix_evaluated", 0) or 0),
        "matrix_failed": int(matrix.get("matrix_failed", 0) or 0),
        "matrix_skipped": int(matrix.get("matrix_skipped", 0) or 0),
        "failure_reasons": list(matrix.get("failure_reasons", []) or []),
    }
    return _canonical_hash(core)


def _strict_semantics_ok(matrix: dict[str, Any], *, expected_total: int) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not bool(matrix.get("ok", False)):
        reasons.append("matrix_ok_false")
    if int(matrix.get("matrix_total", 0) or 0) != int(expected_total):
        reasons.append("matrix_total_mismatch")
    if int(matrix.get("matrix_evaluated", 0) or 0) != int(expected_total):
        reasons.append("matrix_evaluated_mismatch")
    if int(matrix.get("matrix_failed", 0) or 0) != 0:
        reasons.append("matrix_failed_nonzero")
    if int(matrix.get("matrix_skipped", 0) or 0) != 0:
        reasons.append("matrix_skipped_nonzero")
    if isinstance(matrix.get("failure_reasons", []), list) and len(matrix.get("failure_reasons", [])) > 0:
        reasons.append("failure_reasons_nonempty")
    return len(reasons) == 0, reasons


def evaluate_runs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    signatures = [str(row.get("signature") or "") for row in rows if str(row.get("signature") or "")]
    unique = sorted(set(signatures))
    all_ok = all(bool(row.get("ok", False)) for row in rows)
    return {
        "ok": bool(all_ok and len(unique) == 1 and len(rows) > 0),
        "runs": len(rows),
        "signatures": signatures,
        "unique_signature_count": len(unique),
        "stable_signature": unique[0] if len(unique) == 1 else "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run strict real-corpus gauntlet N times and fail on drift.")
    parser.add_argument("--runner", default="tools/run_real_corpus_readiness.py")
    parser.add_argument("--contract", default="docs/contracts/real_corpus_expected_answers_v1.json")
    parser.add_argument("--advanced-json", default="")
    parser.add_argument("--generic-json", default="")
    parser.add_argument("--out", default="artifacts/real_corpus/gate_real_corpus_determinism.json")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--expected-total", type=int, default=20)
    parser.add_argument("--matrix-json", action="append", default=[])
    args = parser.parse_args(argv)

    run_count = max(1, int(args.runs))
    rows: list[dict[str, Any]]
    mode = "runner"
    matrix_paths = [Path(str(p)) for p in (args.matrix_json or []) if str(p).strip()]
    if matrix_paths:
        mode = "artifact"
        rows = []
        for idx, path in enumerate(matrix_paths):
            matrix_obj: dict[str, Any] = {}
            if path.exists():
                matrix_obj = json.loads(path.read_text(encoding="utf-8"))
            strict_ok, strict_reasons = _strict_semantics_ok(matrix_obj, expected_total=int(args.expected_total))
            signature = _matrix_signature(matrix_obj) if matrix_obj else ""
            rows.append(
                {
                    "run_index": idx + 1,
                    "returncode": 0 if path.exists() else 1,
                    "elapsed_s": 0.0,
                    "ok": bool(path.exists() and strict_ok and bool(signature)),
                    "matrix": str(path),
                    "strict_semantics_ok": bool(strict_ok),
                    "strict_reasons": strict_reasons if path.exists() else ["matrix_missing"],
                    "signature": signature,
                }
            )
        run_count = len(matrix_paths) if matrix_paths else run_count
    else:
        runner = Path(str(args.runner))
        if not runner.exists():
            print(json.dumps({"ok": False, "error": "runner_not_found", "runner": str(runner)}))
            return 2
        rows = []
        for idx in range(run_count):
            run_out = Path(f"artifacts/real_corpus_gauntlet/determinism_run_{idx+1}_matrix.json")
            cmd = [
                "python3",
                str(runner),
                "--contract",
                str(args.contract),
                "--out",
                str(run_out),
                "--latest-report-md",
                f"artifacts/real_corpus_gauntlet/determinism_run_{idx+1}_latest.md",
            ]
            if str(args.advanced_json).strip():
                cmd.extend(["--advanced-json", str(args.advanced_json).strip()])
            if str(args.generic_json).strip():
                cmd.extend(["--generic-json", str(args.generic_json).strip()])
            t0 = time.monotonic()
            proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
            elapsed_s = time.monotonic() - t0
            payload = _extract_last_json(f"{proc.stdout}\n{proc.stderr}")
            matrix_path = run_out
            matrix_obj: dict[str, Any] = {}
            if matrix_path.exists():
                matrix_obj = json.loads(matrix_path.read_text(encoding="utf-8"))
            strict_ok, strict_reasons = _strict_semantics_ok(matrix_obj, expected_total=int(args.expected_total))
            signature = _matrix_signature(matrix_obj) if matrix_obj else ""
            rows.append(
                {
                    "run_index": idx + 1,
                    "returncode": int(proc.returncode),
                    "elapsed_s": round(float(elapsed_s), 3),
                    "ok": bool(proc.returncode == 0 and bool(payload.get("ok", False)) and strict_ok and bool(signature)),
                    "runner_payload": payload,
                    "matrix": str(matrix_path) if matrix_path.exists() else "",
                    "strict_semantics_ok": bool(strict_ok),
                    "strict_reasons": strict_reasons,
                    "signature": signature,
                }
            )

    summary = evaluate_runs(rows)
    count_ok = len(rows) == int(run_count)
    out_payload = {
        "ok": bool(summary["ok"] and count_ok),
        "mode": mode,
        "required_runs": int(run_count),
        "observed_runs": int(len(rows)),
        "rows": rows,
        "summary": summary,
    }
    out_path = Path(str(args.out))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_payload, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": bool(out_payload["ok"]),
                "out": str(out_path),
                "runs": int(run_count),
                "observed_runs": int(len(rows)),
                "unique_signature_count": int(summary["unique_signature_count"]),
            },
            sort_keys=True,
        )
    )
    return 0 if bool(out_payload["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
