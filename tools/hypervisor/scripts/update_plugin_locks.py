"""Update plugin lockfile hashes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from autocapture_nx.kernel.hashing import sha256_directory, sha256_file


def update_plugin_locks() -> dict:
    root = Path("plugins")
    plugins = {}
    for manifest_path in root.rglob("plugin.json"):
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        plugin_id = manifest["plugin_id"]
        plugin_root = manifest_path.parent
        plugins[plugin_id] = {
            "manifest_sha256": sha256_file(manifest_path),
            "artifact_sha256": sha256_directory(plugin_root),
        }
    lockfile = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plugins": dict(sorted(plugins.items())),
    }
    lock_path = Path("config") / "plugin_locks.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as handle:
        json.dump(lockfile, handle, indent=2, sort_keys=True)
    return lockfile


if __name__ == "__main__":
    update_plugin_locks()
