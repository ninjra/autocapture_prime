"""Frozen surface gate and churn report."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from autocapture.core.hashing import canonical_dumps, hash_canonical
from autocapture_nx.kernel.canonical_json import dumps as nx_canonical_dumps
from autocapture_nx.kernel.hashing import sha256_file
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.egress_sanitizer.plugin import EgressSanitizer
from plugins.builtin.time_advanced.plugin import TimeIntentParser


BASELINE_PATH = Path("contracts/frozen_surfaces.json")
REPORT_PATH = Path("artifacts/frozen_surface_report.json")


@dataclass(frozen=True)
class Change:
    surface: str
    item: str
    status: str
    expected: str | None
    actual: str | None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_cases() -> dict[str, dict[str, Any]]:
    return {
        "simple_map": {"input": {"b": 2, "a": 1}},
        "unicode_norm": {"input": {"text": "e\u0301"}},
        "nested": {"input": {"alpha": [1, 2, {"z": "ok", "a": "ok"}]}},
    }


def _time_cases() -> dict[str, dict[str, Any]]:
    base_now = datetime(2026, 1, 24, 12, 0, 0, tzinfo=timezone.utc)
    return {
        "last_2_hours": {"input": "last 2 hours", "now": base_now.isoformat()},
        "iso_date": {"input": "2026-01-01", "now": base_now.isoformat()},
        "between_dates": {"input": "between 2026-01-01 and 2026-01-03", "now": base_now.isoformat()},
        "today": {"input": "today", "now": base_now.isoformat()},
        "yesterday": {"input": "yesterday", "now": base_now.isoformat()},
        "tomorrow": {"input": "tomorrow", "now": base_now.isoformat()},
    }


def _sanitizer_cases() -> dict[str, dict[str, Any]]:
    return {
        "pii_mix": {
            "text": "Contact John Doe at john@example.com or 555-123-4567. SSN 123-45-6789.",
            "scope": "default",
        },
        "card_url": {
            "text": "Charge 4111 1111 1111 1111 at https://example.com.",
            "scope": "default",
        },
    }


def _build_time_parser() -> TimeIntentParser:
    config = {
        "time": {
            "timezone": "UTC",
            "dst_tie_breaker": "earliest",
            "relative_window_max_days": 30,
        }
    }
    ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
    return TimeIntentParser("frozen.time", ctx)


def _build_sanitizer(tmp_dir: str) -> EgressSanitizer:
    root_key = b"frozen_surface_key_v1".ljust(32, b"_")
    data_dir = tmp_dir.replace("\\", "/")
    root_path = Path(data_dir) / "root.key"
    root_path.write_bytes(root_key)
    config = {
        "storage": {
            "data_dir": data_dir,
            "crypto": {
                "keyring_path": f"{data_dir}/keyring.json",
                "root_key_path": f"{data_dir}/root.key",
            },
        },
        "privacy": {
            "egress": {
                "token_format": "⟦ENT:{type}:{token}⟧",
                "recognizers": {
                    "ssn": True,
                    "credit_card": True,
                    "email": True,
                    "phone": True,
                    "ipv4": True,
                    "url": True,
                    "filepath": True,
                    "names": True,
                    "custom_regex": [],
                },
            }
        },
    }
    ctx = PluginContext(config=config, get_capability=lambda _k: (_ for _ in ()).throw(Exception()), logger=lambda _m: None)
    return EgressSanitizer("frozen.sanitizer", ctx)


def _compute_canonical_section() -> dict[str, Any]:
    cases = _canonical_cases()
    results: dict[str, Any] = {}
    for case_id, payload in cases.items():
        text = canonical_dumps(payload["input"])
        nx_text = nx_canonical_dumps(payload["input"])
        if text != nx_text:
            raise RuntimeError(f"Canonical JSON mismatch for {case_id}")
        results[case_id] = {
            "input": payload["input"],
            "canonical": text,
            "hash": _sha256_text(text),
        }
    return {"cases": results}


def _compute_time_section() -> dict[str, Any]:
    parser = _build_time_parser()
    results: dict[str, Any] = {}
    for case_id, payload in _time_cases().items():
        now = datetime.fromisoformat(payload["now"])
        output = parser.parse(payload["input"], now=now)
        results[case_id] = {
            "input": payload["input"],
            "now": payload["now"],
            "output": output,
            "hash": hash_canonical(output),
        }
    return {"cases": results}


def _compute_token_format_section() -> dict[str, Any]:
    default_cfg = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
    fmt = default_cfg.get("privacy", {}).get("egress", {}).get("token_format", "⟦ENT:{type}:{token}⟧")
    return {"format": fmt, "hash": _sha256_text(fmt)}


def _compute_sanitizer_section() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        sanitizer = _build_sanitizer(tmp)
        results: dict[str, Any] = {}
        for case_id, payload in _sanitizer_cases().items():
            text = payload["text"]
            scope = payload.get("scope", "default")
            sanitized = sanitizer.sanitize_text(text, scope=scope)
            leak_ok = sanitizer.leak_check({"text": sanitized["text"], "_tokens": sanitized["tokens"]})
            detok = sanitizer.detokenize_text(sanitized["text"])
            results[case_id] = {
                "input": {"text": text, "scope": scope},
                "output": {
                    "text": sanitized["text"],
                    "glossary": sanitized["glossary"],
                    "tokens": sanitized["tokens"],
                    "leak_ok": leak_ok,
                    "detokenized": detok,
                },
                "hash": hash_canonical(
                    {
                        "text": sanitized["text"],
                        "glossary": sanitized["glossary"],
                        "tokens": sanitized["tokens"],
                        "leak_ok": leak_ok,
                        "detokenized": detok,
                    }
                ),
            }
    return {"cases": results}


def compute_surfaces() -> dict[str, Any]:
    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "canonical_json": _compute_canonical_section(),
        "time_intent": _compute_time_section(),
        "token_format": _compute_token_format_section(),
        "sanitizer": _compute_sanitizer_section(),
    }


def _load_baseline() -> dict[str, Any]:
    if not BASELINE_PATH.exists():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _check_contract_lock() -> tuple[bool, list[dict[str, str]]]:
    lock_path = Path("contracts/lock.json")
    if not lock_path.exists():
        return False, [{"path": "contracts/lock.json", "error": "missing"}]
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    mismatches: list[dict[str, str]] = []
    for rel, expected in lock.get("files", {}).items():
        actual = sha256_file(rel)
        if actual != expected:
            mismatches.append({"path": rel, "expected": expected, "actual": actual})
    return len(mismatches) == 0, mismatches


def _compare_section(changes: list[Change], surface: str, baseline: dict[str, Any], current: dict[str, Any]) -> None:
    base_cases = baseline.get("cases", {})
    cur_cases = current.get("cases", {})
    for case_id, base_case in base_cases.items():
        if case_id not in cur_cases:
            changes.append(Change(surface, case_id, "missing", base_case.get("hash"), None))
            continue
        base_hash = base_case.get("hash")
        cur_hash = cur_cases[case_id].get("hash")
        if base_hash != cur_hash:
            changes.append(Change(surface, case_id, "changed", base_hash, cur_hash))
    for case_id, cur_case in cur_cases.items():
        if case_id not in base_cases:
            changes.append(Change(surface, case_id, "extra", None, cur_case.get("hash")))


def compare_surfaces(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    changes: list[Change] = []
    for section in ("canonical_json", "time_intent", "sanitizer"):
        _compare_section(changes, section, baseline.get(section, {}), current.get(section, {}))

    base_token = baseline.get("token_format", {}).get("hash")
    cur_token = current.get("token_format", {}).get("hash")
    if base_token is None:
        changes.append(Change("token_format", "token_format", "missing", None, cur_token))
    elif base_token != cur_token:
        changes.append(Change("token_format", "token_format", "changed", base_token, cur_token))

    schema_ok, schema_mismatches = _check_contract_lock()

    report = {
        "ok": len(changes) == 0 and schema_ok,
        "churn": {
            "changed": sum(1 for c in changes if c.status == "changed"),
            "missing": sum(1 for c in changes if c.status == "missing"),
            "extra": sum(1 for c in changes if c.status == "extra"),
        },
        "changes": [c.__dict__ for c in changes],
        "schema_ok": schema_ok,
        "schema_mismatches": schema_mismatches,
    }
    return report


def write_report(report: dict[str, Any], current: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(report)
    payload["current"] = current
    REPORT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def update_baseline(current: dict[str, Any]) -> None:
    BASELINE_PATH.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true", help="write current surfaces to baseline")
    args = parser.parse_args()

    current = compute_surfaces()
    if args.update:
        update_baseline(current)
        report = {"ok": True, "churn": {"changed": 0, "missing": 0, "extra": 0}, "changes": [], "schema_ok": True, "schema_mismatches": []}
        write_report(report, current)
        return 0

    baseline = _load_baseline()
    report = compare_surfaces(baseline, current)
    write_report(report, current)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
