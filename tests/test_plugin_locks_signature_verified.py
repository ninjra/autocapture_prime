from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_plugin_lockfile_signature_verifies_and_registry_enforces(tmp_path: Path):
    from autocapture_nx.kernel.keyring import KeyRing
    from autocapture_nx.plugin_system.lock_signing import sign_lockfile
    from autocapture_nx.plugin_system.registry import PluginRegistry, PluginError

    lock_path = tmp_path / "plugin_locks.json"
    sig_path = tmp_path / "plugin_locks.sig.json"
    keyring_path = tmp_path / "keyring.json"

    lock_path.write_text(json.dumps({"version": 1, "plugins": {}}, sort_keys=True, indent=2), encoding="utf-8")
    keyring = KeyRing.load(str(keyring_path), legacy_root_path=str(tmp_path / "root.key"), backend="portable_file")
    sign_lockfile(lock_path=lock_path, sig_path=sig_path, keyring=keyring)

    cfg = {
        "storage": {
            "crypto": {
                "keyring_path": str(keyring_path),
                "root_key_path": str(tmp_path / "root.key"),
                "keyring_backend": "portable_file",
                "keyring_credential_name": "autocapture.keyring.test",
            }
        },
        "plugins": {
            "locks": {
                "enforce": False,
                "lockfile": str(lock_path),
                "signature": {"enforce": True, "path": str(sig_path)},
            }
        },
    }
    reg = PluginRegistry(cfg, safe_mode=True)
    loaded = reg.load_lockfile()
    assert loaded.get("version") == 1

    # Corrupt signature => load_lockfile rejects.
    sig = json.loads(sig_path.read_text(encoding="utf-8"))
    sig["signature_hex"] = "0" * 64
    sig_path.write_text(json.dumps(sig, sort_keys=True, indent=2), encoding="utf-8")
    reg2 = PluginRegistry(cfg, safe_mode=True)
    with pytest.raises(PluginError):
        reg2.load_lockfile()

