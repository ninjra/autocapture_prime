#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _profile_payload(profile: str) -> dict[str, Any]:
    p = str(profile or "").strip().lower()
    # Minimal allowlist for capture+ingest-only soak:
    # Keep plugin load stable and avoid unrelated providers (embedder/VLM/etc)
    # that may require local model bundle directories.
    allowlist_min = [
        "builtin.anchor.basic",
        "builtin.journal.basic",
        "builtin.ledger.basic",
        "builtin.observability.basic",
        "builtin.storage.encrypted",
        "builtin.capture.screenshot.windows",
        "builtin.tracking.input.windows",
        "builtin.window.metadata.windows",
    ]
    if p == "smoke_screenshot_ingest":
        # Make the smoke check deterministic: force at least one write by disabling
        # dedupe temporarily (short run), while keeping screenshot cadence.
        return {
            "storage": {
                # Allow non-SQLite metadata backends for capture/ingest soak.
                "metadata_require_db": False,
            },
            "plugins": {
                "allowlist": allowlist_min,
                # Soak runs force in-proc hosting to avoid subprocess storms;
                # explicitly allow in-proc loading of enabled plugins.
                "hosting": {"inproc_allow_all": True},
                "enabled": {
                    # SQLCipher is optional and often painful on Windows; use the
                    # AES-GCM encrypted store for soak reliability.
                    "builtin.storage.sqlcipher": False,
                    "builtin.storage.encrypted": True,
                }
            },
            "processing": {"idle": {"enabled": False}},
            "capture": {
                "audio": {"enabled": False},
                "video": {"enabled": False},
                "input_tracking": {"mode": "win32_idle"},
                "window_metadata": {"enabled": True},
                "screenshot": {
                    "enabled": True,
                    # Force deterministic smoke evidence even if the operator is idle
                    # (activity policy would otherwise switch to 60s interval).
                    "activity": {"enabled": False},
                    "dedupe": {"enabled": False},
                },
            },
        }
    if p == "soak_screenshot_only":
        return {
            "storage": {
                "metadata_require_db": False,
            },
            "plugins": {
                "allowlist": allowlist_min,
                "hosting": {"inproc_allow_all": True},
                "enabled": {
                    "builtin.storage.sqlcipher": False,
                    "builtin.storage.encrypted": True,
                }
            },
            "processing": {"idle": {"enabled": False}},
            "capture": {
                "audio": {"enabled": False},
                "video": {"enabled": False},
                "input_tracking": {"mode": "win32_idle"},
                "window_metadata": {"enabled": True},
                "screenshot": {
                    "enabled": True,
                    "dedupe": {"enabled": True},
                },
            },
        }
    raise SystemExit(f"unknown profile: {profile}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config-dir", required=True)
    ap.add_argument("--profile", required=True, choices=["smoke_screenshot_ingest", "soak_screenshot_only"])
    args = ap.parse_args()

    config_dir = Path(args.config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    user_path = config_dir / "user.json"

    payload = _profile_payload(args.profile)
    text = json.dumps(payload, indent=2, sort_keys=True)
    user_path.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
