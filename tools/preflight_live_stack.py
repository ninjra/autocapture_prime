#!/usr/bin/env python3
"""Preflight checks for live sidecar + localhost VLM operational validation."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from autocapture_nx.inference.vllm_endpoint import check_external_vllm_ready, enforce_external_vllm_base_url


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataroot", default="/mnt/d/autocapture")
    parser.add_argument("--vllm-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout-s", type=float, default=3.0)
    parser.add_argument("--output", default="artifacts/live_stack/preflight_latest.json")
    args = parser.parse_args(argv)

    dataroot = Path(str(args.dataroot)).expanduser()
    media_dir = dataroot / "media"
    journal = dataroot / "journal.ndjson"
    metadata_db = dataroot / "metadata.db"
    ledger = dataroot / "ledger.ndjson"

    media_files = 0
    if media_dir.exists() and media_dir.is_dir():
        try:
            for _ in media_dir.rglob("*"):
                media_files += 1
                if media_files >= 1000:
                    break
        except Exception:
            media_files = 0

    base_in = str(args.vllm_base_url).rstrip("/")
    if not base_in.endswith("/v1"):
        base_in = f"{base_in}/v1"
    preflight_base = enforce_external_vllm_base_url(base_in)
    os.environ["AUTOCAPTURE_VLM_BASE_URL"] = preflight_base
    preflight = check_external_vllm_ready(
        require_completion=True,
        timeout_models_s=float(args.timeout_s),
        timeout_completion_s=max(6.0, float(args.timeout_s)),
        retries=1,
        auto_recover=False,
    )

    checks = [
        {"name": "dataroot_exists", "ok": dataroot.exists(), "required": True, "detail": str(dataroot)},
        {"name": "journal_exists", "ok": journal.exists(), "required": False, "detail": str(journal)},
        {"name": "ledger_exists", "ok": ledger.exists(), "required": False, "detail": str(ledger)},
        {"name": "metadata_db_exists", "ok": metadata_db.exists(), "required": True, "detail": str(metadata_db)},
        {"name": "media_dir_exists", "ok": media_dir.exists(), "required": True, "detail": str(media_dir)},
        {"name": "media_has_files", "ok": media_files > 0, "required": True, "detail": media_files},
        {"name": "vllm_preflight", "ok": bool(preflight.get("ok", False)), "required": True, "detail": preflight},
    ]
    ready = all(bool(item["ok"]) for item in checks if bool(item.get("required", False)))
    payload = {
        "schema_version": 1,
        "ts_utc": _utc_now(),
        "dataroot": str(dataroot),
        "vllm_base_url": str(preflight_base),
        "ready": bool(ready),
        "checks": checks,
    }

    out = Path(str(args.output))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": bool(ready), "output": str(out)}, sort_keys=True))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
