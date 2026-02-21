#!/usr/bin/env python3
"""Validate a Mode-B (Shared DataRoot) sidecar dataset for autocapture_prime.

This is intentionally read-only. It helps the Windows sidecar repo converge on
the on-disk contract in docs/windows-sidecar-capture-interface.md.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _first_existing(paths: list[Path]) -> Path | None:
    for p in paths:
        try:
            if p.exists():
                return p
        except Exception:
            continue
    return None


def _inspect_metadata_db(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"path": str(path), "ok": False}
    try:
        con = sqlite3.connect(str(path))
    except Exception as exc:
        out["error"] = f"open_failed:{type(exc).__name__}:{exc}"
        return out
    try:
        cur = con.cursor()
        cur.execute("select name from sqlite_master where type='table'")
        tables = sorted([r[0] for r in cur.fetchall() if r and r[0]])
        out["tables"] = tables
        schema: dict[str, list[dict[str, Any]]] = {}
        for t in tables:
            try:
                cur.execute(f"pragma table_info({t})")
                cols = cur.fetchall()
            except Exception:
                continue
            schema[t] = [{"name": c[1], "type": c[2]} for c in cols if c and len(c) >= 3]
        out["schema"] = schema

        want = {"evidence.capture.frame", "derived.input.summary"}

        # Preferred contract: plaintext metadata table with JSON payload and index columns.
        metadata_cols = {c.get("name") for c in schema.get("metadata", []) if isinstance(c, dict)}
        out["metadata_mode"] = "unknown"
        if {"id", "payload", "record_type", "ts_utc", "run_id"}.issubset(metadata_cols):
            out["metadata_mode"] = "plain_metadata_table"
            cur.execute("select count(*) from metadata")
            out["metadata_rows"] = int(cur.fetchone()[0])
            cur.execute("select record_type, count(*) from metadata group by record_type order by count(*) desc limit 15")
            out["top_record_types"] = [{"record_type": r[0], "count": int(r[1])} for r in cur.fetchall()]
            got = {str(item.get("record_type")) for item in out.get("top_record_types", []) if isinstance(item, dict) and item.get("record_type")}
            out["has_minimum_record_types"] = bool(want.issubset(got))
            out["missing_record_types"] = sorted([t for t in want if t not in got])
            out["ok"] = bool(out.get("metadata_rows", 0) > 0 and out["has_minimum_record_types"])
            return out

        # Common sidecar mismatch: encrypted metadata table + plaintext `records` table.
        if {"nonce_b64", "ciphertext_b64", "key_id"}.issubset(metadata_cols):
            out["metadata_mode"] = "encrypted_metadata_table"
            try:
                cur.execute("select count(*) from metadata")
                out["metadata_rows"] = int(cur.fetchone()[0])
            except Exception:
                pass

        records_cols = {c.get("name") for c in schema.get("records", []) if isinstance(c, dict)}
        if {"id", "record_type", "ts_utc", "json"}.issubset(records_cols):
            out["records_table_present"] = True
            try:
                cur.execute("select count(*) from records")
                out["records_rows"] = int(cur.fetchone()[0])
                cur.execute("select record_type, count(*) from records group by record_type order by count(*) desc limit 15")
                out["top_record_types_records"] = [{"record_type": r[0], "count": int(r[1])} for r in cur.fetchall()]
                got = {str(item.get("record_type")) for item in out.get("top_record_types_records", []) if isinstance(item, dict) and item.get("record_type")}
                out["has_minimum_record_types_records"] = bool(want.issubset(got))
                out["missing_record_types_records"] = sorted([t for t in want if t not in got])
            except Exception:
                pass
            out["ok"] = False
            out["error"] = "metadata_schema_mismatch"
            out["recommended_fix"] = (
                "For Mode B, write a plaintext metadata table: "
                "metadata(id TEXT PRIMARY KEY, payload TEXT NOT NULL, record_type TEXT, ts_utc TEXT, run_id TEXT). "
                "Do not use encrypted metadata unless the processor has the keyring."
            )
            return out

        out["ok"] = False
        out["error"] = "metadata_schema_unknown"
        return out
    finally:
        try:
            con.close()
        except Exception:
            pass


def _inspect_journal(path: Path, *, max_lines: int) -> dict[str, Any]:
    out: dict[str, Any] = {"path": str(path), "ok": False, "max_lines": int(max_lines)}
    try:
        counter = Counter()
        record_types = Counter()
        seen = 0
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if seen >= max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                seen += 1
                et = obj.get("event_type")
                if et:
                    counter[str(et)] += 1
                payload = obj.get("payload")
                if isinstance(payload, dict) and payload.get("record_type"):
                    record_types[str(payload.get("record_type"))] += 1
        out["lines_parsed"] = int(seen)
        out["top_event_types"] = [{"event_type": k, "count": int(v)} for k, v in counter.most_common(20)]
        out["top_payload_record_types"] = [{"record_type": k, "count": int(v)} for k, v in record_types.most_common(20)]
        out["ok"] = True
        return out
    except Exception as exc:
        out["error"] = f"read_failed:{type(exc).__name__}:{exc}"
        return out


def _media_summary(root: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"path": str(root), "ok": False}
    try:
        if not root.exists():
            out["error"] = "missing"
            return out
        exts = Counter()
        total = 0
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            total += 1
            exts[p.suffix.lower() or "<none>"] += 1
            if total >= 10_000:
                break
        out["files_sampled_cap"] = 10_000
        out["files_count_sampled"] = int(total)
        out["ext_counts_sampled"] = [{"ext": k, "count": int(v)} for k, v in exts.most_common(20)]
        out["has_blob_files"] = bool(exts.get(".blob", 0) > 0 or exts.get(".stream", 0) > 0)
        out["ok"] = bool(out["has_blob_files"])
        return out
    except Exception as exc:
        out["error"] = f"scan_failed:{type(exc).__name__}:{exc}"
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataroot", required=True, help="Shared DataRoot path (Mode B)")
    ap.add_argument("--max-journal-lines", type=int, default=20000)
    ap.add_argument(
        "--contract-profile",
        choices=["strict", "metadata_first"],
        default="strict",
        help="Validation profile: strict requires journal+ledger; metadata_first requires activity+media+metadata.",
    )
    args = ap.parse_args()

    dataroot = Path(str(args.dataroot))
    report: dict[str, Any] = {
        "ok": False,
        "dataroot": str(dataroot),
        "contract_profile": str(args.contract_profile),
        "checks": {},
    }

    activity_path = _first_existing([dataroot / "activity" / "activity_signal.json", dataroot / "activity_signal.json"])
    report["checks"]["activity_signal"] = {
        "present": activity_path is not None,
        "path": str(activity_path) if activity_path is not None else None,
        "payload": _read_json(activity_path) if activity_path is not None else None,
    }

    journal_path = dataroot / "journal.ndjson"
    ledger_path = dataroot / "ledger.ndjson"
    report["checks"]["journal"] = _inspect_journal(journal_path, max_lines=int(args.max_journal_lines)) if journal_path.exists() else {"path": str(journal_path), "ok": False, "error": "missing"}
    report["checks"]["ledger"] = {"path": str(ledger_path), "present": ledger_path.exists()}

    meta_path = _first_existing([dataroot / "metadata" / "metadata.db", dataroot / "metadata.db"])
    report["checks"]["metadata_db"] = (
        _inspect_metadata_db(meta_path)
        if meta_path is not None
        else {
            "ok": False,
            "error": "missing",
            "candidates": [str(dataroot / "metadata" / "metadata.db"), str(dataroot / "metadata.db")],
        }
    )

    media_dir = _first_existing([dataroot / "media", dataroot / "data" / "media"])
    report["checks"]["media"] = (
        _media_summary(media_dir)
        if media_dir is not None
        else {
            "ok": False,
            "error": "missing",
            "candidates": [str(dataroot / "media"), str(dataroot / "data" / "media")],
        }
    )

    activity_ok = bool(report["checks"]["activity_signal"]["present"])
    journal_ok = bool(report["checks"]["journal"].get("ok"))
    ledger_ok = bool(report["checks"]["ledger"]["present"])
    metadata_ok = bool(report["checks"]["metadata_db"].get("ok"))
    media_ok = bool(report["checks"]["media"].get("ok"))
    strict_ok = bool(activity_ok and journal_ok and ledger_ok and metadata_ok and media_ok)
    metadata_first_ok = bool(activity_ok and metadata_ok and media_ok)
    report["profiles"] = {"strict": strict_ok, "metadata_first": metadata_first_ok}
    if str(args.contract_profile) == "metadata_first":
        warnings: list[str] = []
        if not journal_ok:
            warnings.append("journal_missing_or_invalid")
        if not ledger_ok:
            warnings.append("ledger_missing")
        if warnings:
            report["warnings"] = warnings
    report["ok"] = bool(report["profiles"].get(str(args.contract_profile), False))

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
