"""Update plugin lockfile hashes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from autocapture_nx import __version__ as kernel_version
from autocapture_nx.kernel.hashing import sha256_directory, sha256_file


def update_plugin_locks() -> dict:
    root = Path("plugins")
    contract_lock = Path("contracts") / "lock.json"
    contract_lock_hash = sha256_file(contract_lock) if contract_lock.exists() else None
    plugins = {}
    for manifest_path in root.rglob("plugin.json"):
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        plugin_id = manifest["plugin_id"]
        plugin_root = manifest_path.parent
        sbom: dict[str, object] = {"requirements": [], "requirements_sha256": None}
        req = plugin_root / "requirements.txt"
        if req.exists():
            try:
                sbom["requirements_sha256"] = sha256_file(req)
                deps = []
                for line in req.read_text(encoding="utf-8").splitlines():
                    raw = line.strip()
                    if not raw or raw.startswith("#"):
                        continue
                    deps.append(raw)
                sbom["requirements"] = deps
            except Exception:
                sbom = {"requirements": [], "requirements_sha256": None}
        plugins[plugin_id] = {
            "kernel_api_version": str(kernel_version),
            "contract_lock_hash": contract_lock_hash,
            "manifest_sha256": sha256_file(manifest_path),
            "artifact_sha256": sha256_directory(plugin_root),
            "sbom": sbom,
        }
    lockfile = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kernel_api_version": str(kernel_version),
        "contract_lock_hash": contract_lock_hash,
        "plugins": dict(sorted(plugins.items())),
    }
    lock_path = Path("config") / "plugin_locks.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as handle:
        json.dump(lockfile, handle, indent=2, sort_keys=True)
    return lockfile


if __name__ == "__main__":
    update_plugin_locks()
