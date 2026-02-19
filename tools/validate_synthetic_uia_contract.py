#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_hash_token(path: Path) -> str | None:
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    token = raw.split()[0].strip().lower()
    if len(token) != 64:
        return None
    if any(ch not in "0123456789abcdef" for ch in token):
        return None
    return token


def validate_pack(pack: dict[str, Any], *, require_hash_match: bool) -> list[str]:
    errors: list[str] = []
    uia_ref = pack.get("uia_ref") if isinstance(pack.get("uia_ref"), dict) else {}
    snapshot = pack.get("snapshot") if isinstance(pack.get("snapshot"), dict) else {}
    metadata_record = pack.get("metadata_record") if isinstance(pack.get("metadata_record"), dict) else {}
    fallback = pack.get("fallback") if isinstance(pack.get("fallback"), dict) else {}

    required_uia_ref = ("record_id", "ts_utc", "content_hash")
    for key in required_uia_ref:
        if not str(uia_ref.get(key) or "").strip():
            errors.append(f"uia_ref_missing_{key}")

    if str(snapshot.get("record_type") or "") != "evidence.uia.snapshot":
        errors.append("snapshot_record_type_invalid")
    for key in ("record_id", "run_id", "ts_utc", "unix_ms_utc", "hwnd", "window", "focus_path", "context_peers", "operables", "stats", "content_hash"):
        if key not in snapshot:
            errors.append(f"snapshot_missing_{key}")

    if str(metadata_record.get("record_type") or "") != "evidence.uia.snapshot":
        errors.append("metadata_record_type_invalid")
    meta_payload = metadata_record.get("payload")
    if not isinstance(meta_payload, dict):
        errors.append("metadata_payload_missing")

    if str(uia_ref.get("record_id") or "").strip() and str(snapshot.get("record_id") or "").strip():
        if str(uia_ref.get("record_id") or "").strip() != str(snapshot.get("record_id") or "").strip():
            errors.append("record_id_mismatch")

    if require_hash_match:
        ref_hash = str(uia_ref.get("content_hash") or "").strip().lower()
        snap_hash = str(snapshot.get("content_hash") or "").strip().lower()
        if ref_hash and snap_hash and ref_hash != snap_hash:
            errors.append("uia_ref_snapshot_hash_mismatch")

    snap_path_raw = str(fallback.get("latest_snap_json") or "").strip()
    hash_path_raw = str(fallback.get("latest_snap_sha256") or "").strip()
    declared_file_hash = str(fallback.get("latest_snap_file_hash") or "").strip().lower()
    if not snap_path_raw:
        errors.append("fallback_latest_snap_json_missing")
    else:
        snap_path = Path(snap_path_raw)
        if not snap_path.exists():
            errors.append("fallback_latest_snap_json_not_found")
        else:
            snap_bytes = snap_path.read_bytes()
            file_hash = hashlib.sha256(snap_bytes).hexdigest().lower()
            if declared_file_hash and declared_file_hash != file_hash:
                errors.append("fallback_file_hash_declared_mismatch")
            if hash_path_raw:
                hash_path = Path(hash_path_raw)
                token = _read_hash_token(hash_path)
                if token is None:
                    errors.append("fallback_sha256_token_invalid")
                elif token != file_hash:
                    errors.append("fallback_sha256_file_mismatch")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate synthetic UIA contract fixtures.")
    parser.add_argument("--pack-json", required=True, help="Path to synthetic_uia_contract_pack.json.")
    parser.add_argument("--require-hash-match", action="store_true", default=True)
    parser.add_argument("--allow-hash-mismatch", dest="require_hash_match", action="store_false")
    args = parser.parse_args()

    pack_path = Path(args.pack_json)
    if not pack_path.exists():
        print(json.dumps({"ok": False, "error": "pack_not_found", "pack_json": str(pack_path)}))
        return 2
    try:
        pack = _read_json(pack_path)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"pack_parse_failed:{type(exc).__name__}", "pack_json": str(pack_path)}))
        return 2

    errors = validate_pack(pack, require_hash_match=bool(args.require_hash_match))
    payload = {
        "ok": len(errors) == 0,
        "pack_json": str(pack_path),
        "require_hash_match": bool(args.require_hash_match),
        "errors": errors,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
