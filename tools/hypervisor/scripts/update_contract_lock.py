"""Update contract lockfile hashes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from autocapture_nx.kernel.hashing import sha256_file


CONTRACT_FILES = [
    "contracts/plugin_sdk.md",
    "contracts/config_schema.json",
    "contracts/user_surface.md",
    "contracts/security.md",
    "contracts/plugin_manifest.schema.json",
    "contracts/ir_pins.json",
    "contracts/journal_schema.json",
    "contracts/ledger_schema.json",
    "contracts/reasoning_packet.schema.json",
    "contracts/time_intent.schema.json",
    "contracts/evidence.schema.json",
    "contracts/citation.schema.json",
    "contracts/sst_stage_input.schema.json",
    "contracts/sst_stage_output.schema.json",
    "contracts/answer_build_input.schema.json",
    "contracts/answer_build_output.schema.json",
    "contracts/state_layer.schema.json",
]


def update_contract_lock() -> dict:
    hashes = {}
    for rel in CONTRACT_FILES:
        path = Path(rel)
        hashes[rel] = sha256_file(path)
    lockfile = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": hashes,
    }
    lock_path = Path("contracts") / "lock.json"
    with open(lock_path, "w", encoding="utf-8") as handle:
        json.dump(lockfile, handle, indent=2, sort_keys=True)
    return lockfile


if __name__ == "__main__":
    update_contract_lock()
