#!/usr/bin/env python3
"""Evaluate OCR text quality against ground-truth fixtures (CER/WER)."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").replace("\r", "\n").split())


def _levenshtein(a: list[str], b: list[str]) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, av in enumerate(a, start=1):
        cur = [i]
        for j, bv in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if av == bv else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def _cer(expected: str, observed: str) -> float:
    exp = list(expected)
    obs = list(observed)
    dist = _levenshtein(exp, obs)
    return float(dist) / float(max(1, len(exp)))


def _wer(expected: str, observed: str) -> float:
    exp = expected.split()
    obs = observed.split()
    dist = _levenshtein(exp, obs)
    return float(dist) / float(max(1, len(exp)))


def _load_cases(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        cases = raw.get("cases", [])
    else:
        cases = raw
    if not isinstance(cases, list):
        raise ValueError("fixture must be a list or {\"cases\": [...]} object")
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(cases):
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("id") or f"case_{idx}")
        expected = _normalize_text(str(item.get("expected_text") or item.get("expected") or ""))
        observed = _normalize_text(str(item.get("observed_text") or item.get("observed") or ""))
        out.append({"id": case_id, "expected": expected, "observed": observed})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", required=True, help="Path to OCR quality fixture json")
    ap.add_argument("--output", default="artifacts/ocr_quality/latest.json")
    ap.add_argument("--max-mean-cer", type=float, default=0.25)
    ap.add_argument("--max-mean-wer", type=float, default=0.35)
    args = ap.parse_args()

    fixture_path = Path(str(args.fixture))
    out_path = Path(str(args.output))
    cases = _load_cases(fixture_path)
    if not cases:
        raise SystemExit("no cases found in fixture")

    rows: list[dict[str, Any]] = []
    cer_values: list[float] = []
    wer_values: list[float] = []
    for case in cases:
        exp = str(case["expected"])
        obs = str(case["observed"])
        cer = _cer(exp, obs)
        wer = _wer(exp, obs)
        cer_values.append(cer)
        wer_values.append(wer)
        rows.append(
            {
                "id": str(case["id"]),
                "expected_len": len(exp),
                "observed_len": len(obs),
                "cer": round(cer, 6),
                "wer": round(wer, 6),
            }
        )

    mean_cer = float(mean(cer_values))
    mean_wer = float(mean(wer_values))
    pass_cer = bool(mean_cer <= float(args.max_mean_cer))
    pass_wer = bool(mean_wer <= float(args.max_mean_wer))
    ok = bool(pass_cer and pass_wer)
    payload = {
        "schema_version": 1,
        "ts_utc": _utc_now(),
        "fixture": str(fixture_path),
        "cases_total": int(len(rows)),
        "thresholds": {"max_mean_cer": float(args.max_mean_cer), "max_mean_wer": float(args.max_mean_wer)},
        "summary": {
            "mean_cer": round(mean_cer, 6),
            "mean_wer": round(mean_wer, 6),
            "pass_cer": pass_cer,
            "pass_wer": pass_wer,
            "ok": ok,
        },
        "rows": rows,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": ok, "output": str(out_path)}, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
