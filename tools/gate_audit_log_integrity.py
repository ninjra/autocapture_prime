#!/usr/bin/env python3
"""Audit log integrity gate for append-only JSONL events."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.hashing import sha256_text


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _hash_payload(obj: dict[str, Any]) -> str:
    return sha256_text(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def evaluate_audit_log(*, path: Path, allow_missing: bool = False) -> dict[str, Any]:
    if not path.exists():
        return {
            "ok": bool(allow_missing),
            "error": "audit_log_missing",
            "counts": {"lines": 0, "valid": 0, "invalid": 0},
            "issues": {} if allow_missing else {"missing": 1},
        }

    raw_lines = path.read_text(encoding="utf-8").splitlines()
    required_fields = ("schema_version", "ts_utc", "action", "actor", "outcome")

    issues = {
        "invalid_json": 0,
        "missing_required_fields": 0,
        "invalid_ts_utc": 0,
        "timestamp_regression": 0,
        "seq_gap_or_mismatch": 0,
        "prev_line_hash_mismatch": 0,
        "line_hash_mismatch": 0,
    }
    previous_ts: datetime | None = None
    previous_payload_hash = ""
    valid_count = 0
    chain_hashes: list[str] = []

    for idx, line in enumerate(raw_lines, start=1):
        text = str(line).strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except Exception:
            issues["invalid_json"] += 1
            continue
        if not isinstance(row, dict):
            issues["invalid_json"] += 1
            continue
        if any(field not in row for field in required_fields):
            issues["missing_required_fields"] += 1
            continue
        ts = _parse_ts(row.get("ts_utc"))
        if ts is None:
            issues["invalid_ts_utc"] += 1
        elif previous_ts is not None and ts < previous_ts:
            issues["timestamp_regression"] += 1
        if ts is not None:
            previous_ts = ts

        seq_val = row.get("seq")
        if seq_val is not None:
            try:
                if int(seq_val) != idx:
                    issues["seq_gap_or_mismatch"] += 1
            except Exception:
                issues["seq_gap_or_mismatch"] += 1

        payload_hash = _hash_payload(row)
        if row.get("line_hash") is not None and str(row.get("line_hash") or "") != payload_hash:
            issues["line_hash_mismatch"] += 1
        prev_ref = str(row.get("prev_line_hash") or "")
        if prev_ref and previous_payload_hash and prev_ref != previous_payload_hash:
            issues["prev_line_hash_mismatch"] += 1
        previous_payload_hash = payload_hash
        chain_hashes.append(payload_hash)
        valid_count += 1

    blocking_keys = {
        "invalid_json",
        "missing_required_fields",
        "invalid_ts_utc",
        "seq_gap_or_mismatch",
        "prev_line_hash_mismatch",
        "line_hash_mismatch",
    }
    nonzero_issues = {key: int(value) for key, value in issues.items() if int(value) > 0}
    blocking_issues = {key: int(value) for key, value in nonzero_issues.items() if key in blocking_keys}
    warnings = {key: int(value) for key, value in nonzero_issues.items() if key not in blocking_keys}
    overall_chain_hash = sha256_text("|".join(chain_hashes)) if chain_hashes else ""
    ok = len(blocking_issues) == 0
    return {
        "ok": bool(ok),
        "log_path": str(path),
        "counts": {
            "lines": int(len(raw_lines)),
            "valid": int(valid_count),
            "invalid": int(max(0, len(raw_lines) - valid_count)),
        },
        "issues": blocking_issues,
        "warnings": warnings,
        "overall_chain_hash": overall_chain_hash,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate append-only audit JSONL integrity.")
    parser.add_argument("--log", default="artifacts/audit/audit.jsonl", help="Audit JSONL path.")
    parser.add_argument("--allow-missing", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--output", default="artifacts/audit/gate_audit_log_integrity.json")
    args = parser.parse_args(argv)

    result = evaluate_audit_log(path=Path(str(args.log)).expanduser(), allow_missing=bool(args.allow_missing))
    payload = {"schema_version": 1, **result}
    out_path = Path(str(args.output)).expanduser()
    _write_json(out_path, payload)
    payload["output"] = str(out_path)
    print(json.dumps(payload, sort_keys=True))
    return 0 if bool(payload.get("ok", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
