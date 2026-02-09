from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_plugin_lock_contract_hash_mismatch_blocked(tmp_path: Path):
    from autocapture_nx.plugin_system.registry import PluginRegistry, PluginError
    from autocapture_nx.kernel.hashing import sha256_directory, sha256_file
    from autocapture_nx import __version__ as kernel_version

    manifest_path = Path("plugins/builtin/retrieval_basic/plugin.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plugin_id = manifest["plugin_id"]
    plugin_root = manifest_path.parent
    lockfile = {
        "version": 1,
        "plugins": {
            plugin_id: {
                "kernel_api_version": str(kernel_version),
                "contract_lock_hash": "0" * 64,
                "manifest_sha256": sha256_file(manifest_path),
                "artifact_sha256": sha256_directory(plugin_root),
                "sbom": {"requirements": [], "requirements_sha256": None},
            }
        },
    }
    cfg = {"plugins": {"locks": {"enforce": True, "lockfile": "config/plugin_locks.json"}}}
    reg = PluginRegistry(cfg, safe_mode=True)
    with pytest.raises(PluginError, match="contract_lock_hash mismatch"):
        reg._check_lock(plugin_id, manifest_path, plugin_root, lockfile)  # type: ignore[attr-defined]


def test_plugin_lock_contract_hash_match_ok():
    from autocapture_nx.plugin_system.registry import PluginRegistry
    from autocapture_nx.kernel.hashing import sha256_directory, sha256_file
    from autocapture_nx import __version__ as kernel_version
    from autocapture_nx.kernel.paths import resolve_repo_path

    manifest_path = Path("plugins/builtin/retrieval_basic/plugin.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plugin_id = manifest["plugin_id"]
    plugin_root = manifest_path.parent
    contract_hash = sha256_file(resolve_repo_path("contracts/lock.json"))
    lockfile = {
        "version": 1,
        "contract_lock_hash": contract_hash,
        "plugins": {
            plugin_id: {
                "kernel_api_version": str(kernel_version),
                "contract_lock_hash": contract_hash,
                "manifest_sha256": sha256_file(manifest_path),
                "artifact_sha256": sha256_directory(plugin_root),
                "sbom": {"requirements": [], "requirements_sha256": None},
            }
        },
    }
    cfg = {"plugins": {"locks": {"enforce": True, "lockfile": "config/plugin_locks.json"}}}
    reg = PluginRegistry(cfg, safe_mode=True)
    reg._check_lock(plugin_id, manifest_path, plugin_root, lockfile)  # type: ignore[attr-defined]
