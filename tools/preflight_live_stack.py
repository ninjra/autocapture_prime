#!/usr/bin/env python3
"""Preflight checks for live sidecar + localhost VLM operational validation."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _http_check(url: str, timeout_s: float) -> dict[str, Any]:
    started = time.perf_counter()
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            _ = resp.read(64)
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
            return {"ok": status in {200, 401, 403}, "status": status, "latency_ms": elapsed_ms, "error": ""}
    except urllib.error.HTTPError as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        status = int(getattr(exc, "code", 0) or 0)
        return {"ok": status in {401, 403}, "status": status, "latency_ms": elapsed_ms, "error": f"http_error:{status}"}
    except Exception as exc:  # pragma: no cover - defensive
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        return {"ok": False, "status": 0, "latency_ms": elapsed_ms, "error": f"{type(exc).__name__}:{exc}"}


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

    health = _http_check(f"{str(args.vllm_base_url).rstrip('/')}/health", float(args.timeout_s))
    models = _http_check(f"{str(args.vllm_base_url).rstrip('/')}/v1/models", float(args.timeout_s))

    checks = [
        {"name": "dataroot_exists", "ok": dataroot.exists(), "required": True, "detail": str(dataroot)},
        {"name": "journal_exists", "ok": journal.exists(), "required": False, "detail": str(journal)},
        {"name": "ledger_exists", "ok": ledger.exists(), "required": False, "detail": str(ledger)},
        {"name": "metadata_db_exists", "ok": metadata_db.exists(), "required": True, "detail": str(metadata_db)},
        {"name": "media_dir_exists", "ok": media_dir.exists(), "required": True, "detail": str(media_dir)},
        {"name": "media_has_files", "ok": media_files > 0, "required": True, "detail": media_files},
        {"name": "vllm_health", "ok": bool(health.get("ok", False)), "required": True, "detail": health},
        {"name": "vllm_models", "ok": bool(models.get("ok", False)), "required": True, "detail": models},
    ]
    ready = all(bool(item["ok"]) for item in checks if bool(item.get("required", False)))
    payload = {
        "schema_version": 1,
        "ts_utc": _utc_now(),
        "dataroot": str(dataroot),
        "vllm_base_url": str(args.vllm_base_url),
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
