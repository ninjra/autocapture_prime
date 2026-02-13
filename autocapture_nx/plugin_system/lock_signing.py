"""Plugin lockfile signing + verification (EXT-11).

We sign the sha256 of the lockfile bytes using an HMAC derived from the
KeyRing anchor key. The signature artifact is stored alongside the lockfile
in the user's config/data directory (not checked into git).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.crypto import derive_key
from autocapture_nx.kernel.keyring import KeyRing


def sign_lockfile(*, lock_path: str | Path, sig_path: str | Path, keyring: KeyRing) -> dict[str, Any]:
    lock_path = Path(lock_path)
    sig_path = Path(sig_path)
    lock_bytes = lock_path.read_bytes()
    lock_sha = hashlib.sha256(lock_bytes).hexdigest()
    key_id, root = keyring.active_key("anchor")
    key = derive_key(root, "plugin_locks")
    sig_hex = hmac.new(key, lock_sha.encode("utf-8"), hashlib.sha256).hexdigest()
    payload = {
        "schema_version": 1,
        "algo": "hmac-sha256",
        "key_id": str(key_id),
        "lockfile_sha256": str(lock_sha),
        "signature_hex": str(sig_hex),
    }
    sig_path.parent.mkdir(parents=True, exist_ok=True)
    sig_path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
    return payload


def verify_lockfile(*, lock_path: str | Path, sig_path: str | Path, keyring: KeyRing) -> dict[str, Any]:
    lock_path = Path(lock_path)
    sig_path = Path(sig_path)
    if not lock_path.exists():
        return {"ok": False, "error": "lockfile_missing"}
    if not sig_path.exists():
        return {"ok": False, "error": "signature_missing"}
    try:
        sig = json.loads(sig_path.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "error": "signature_invalid_json"}
    if not isinstance(sig, dict):
        return {"ok": False, "error": "signature_invalid_shape"}
    if sig.get("algo") != "hmac-sha256":
        return {"ok": False, "error": "signature_algo_unsupported"}
    lock_bytes = lock_path.read_bytes()
    lock_sha = hashlib.sha256(lock_bytes).hexdigest()
    if str(sig.get("lockfile_sha256") or "") != lock_sha:
        return {"ok": False, "error": "lockfile_sha256_mismatch"}
    key_id = str(sig.get("key_id") or "").strip()
    sig_hex = str(sig.get("signature_hex") or "").strip()
    if not key_id or not sig_hex:
        return {"ok": False, "error": "signature_missing_fields"}
    try:
        root = keyring.key_for("anchor", key_id)
        key = derive_key(root, "plugin_locks")
    except Exception:
        return {"ok": False, "error": "signature_key_unavailable"}
    expected = hmac.new(key, lock_sha.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig_hex):
        return {"ok": False, "error": "signature_mismatch"}
    return {"ok": True, "key_id": key_id, "lockfile_sha256": lock_sha}

