#!/usr/bin/env python3
"""Preflight checks for live sidecar + localhost VLM operational validation."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from autocapture_nx.inference.vllm_endpoint import check_external_vllm_ready, enforce_external_vllm_base_url
from autocapture_nx.kernel.db_status import metadata_db_stability_snapshot
from autocapture_nx.runtime.http_localhost import request_json
from autocapture_nx.runtime.service_ports import (
    EMBEDDER_BASE_URL,
    GROUNDING_BASE_URL,
    HYPERVISOR_GATEWAY_BASE_URL,
    POPUP_QUERY_BASE_URL,
    VLM_ROOT_URL,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _check_row(*, name: str, ok: bool, required: bool, detail: object, failure_code: str) -> dict[str, object]:
    return {
        "name": str(name),
        "ok": bool(ok),
        "required": bool(required),
        "detail": detail,
        "failure_code": str(failure_code),
    }


def _http_probe(url: str, timeout_s: float) -> dict[str, object]:
    out = request_json(method="GET", url=str(url), timeout_s=float(timeout_s))
    status = int(out.get("status", 0) or 0)
    err = str(out.get("error") or "").strip()
    return {
        "ok": bool(out.get("ok", False)),
        "status": status,
        "url": str(url),
        "error": err,
        "transport": str(out.get("transport") or ""),
    }


def _probe_service_contracts(timeout_s: float) -> dict[str, dict[str, object]]:
    timeout = max(0.5, float(timeout_s))
    return {
        "vllm_models": _http_probe(f"{VLM_ROOT_URL.rstrip('/')}/v1/models", timeout),
        "embedder_models": _http_probe(f"{EMBEDDER_BASE_URL.rstrip('/')}/v1/models", timeout),
        "grounding_health": _http_probe(f"{GROUNDING_BASE_URL.rstrip('/')}/health", timeout),
        "hypervisor_statusz": _http_probe(f"{HYPERVISOR_GATEWAY_BASE_URL.rstrip('/')}/statusz", timeout),
        "popup_health": _http_probe(f"{POPUP_QUERY_BASE_URL.rstrip('/')}/health", timeout),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataroot", default="/mnt/d/autocapture")
    parser.add_argument("--vllm-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout-s", type=float, default=3.0)
    parser.add_argument("--db-stability-samples", type=int, default=3)
    parser.add_argument("--db-stability-interval-ms", type=int, default=250)
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
    completion_timeout_s = max(
        12.0,
        float(
            os.environ.get("AUTOCAPTURE_LIVE_PREFLIGHT_COMPLETION_TIMEOUT_S")
            or os.environ.get("AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S")
            or 30.0
        ),
    )
    live_retries = int(
        os.environ.get("AUTOCAPTURE_LIVE_PREFLIGHT_RETRIES")
        or os.environ.get("AUTOCAPTURE_VLM_PREFLIGHT_RETRIES")
        or 3
    )
    live_retries = max(1, min(8, live_retries))
    preflight = check_external_vllm_ready(
        require_completion=True,
        timeout_models_s=float(args.timeout_s),
        timeout_completion_s=completion_timeout_s,
        retries=live_retries,
        auto_recover=True,
    )
    service_contract = _probe_service_contracts(float(args.timeout_s))
    db_stability = metadata_db_stability_snapshot(
        {"storage": {"metadata_path": str(metadata_db)}},
        sample_count=int(args.db_stability_samples),
        poll_interval_ms=int(args.db_stability_interval_ms),
    )

    checks = [
        _check_row(
            name="dataroot_exists",
            ok=dataroot.exists(),
            required=True,
            detail=str(dataroot),
            failure_code="dataroot_missing",
        ),
        _check_row(
            name="journal_exists",
            ok=journal.exists(),
            required=False,
            detail=str(journal),
            failure_code="journal_missing",
        ),
        _check_row(
            name="ledger_exists",
            ok=ledger.exists(),
            required=False,
            detail=str(ledger),
            failure_code="ledger_missing",
        ),
        _check_row(
            name="metadata_db_exists",
            ok=metadata_db.exists(),
            required=True,
            detail=str(metadata_db),
            failure_code="metadata_db_missing",
        ),
        _check_row(
            name="metadata_db_stable",
            ok=bool(db_stability.get("ok", False)),
            required=True,
            detail=db_stability,
            failure_code="metadata_db_unstable",
        ),
        _check_row(
            name="media_dir_exists",
            ok=media_dir.exists(),
            required=True,
            detail=str(media_dir),
            failure_code="media_dir_missing",
        ),
        _check_row(
            name="media_has_files",
            ok=media_files > 0,
            required=True,
            detail=media_files,
            failure_code="media_empty",
        ),
        _check_row(
            name="vllm_preflight",
            ok=bool(preflight.get("ok", False)),
            required=True,
            detail=preflight,
            failure_code="vllm_preflight_failed",
        ),
        _check_row(
            name="svc.vllm_models",
            ok=bool(service_contract.get("vllm_models", {}).get("ok", False)),
            required=True,
            detail=service_contract.get("vllm_models", {}),
            failure_code="svc_vllm_models_unreachable",
        ),
        _check_row(
            name="svc.embedder_models",
            ok=bool(service_contract.get("embedder_models", {}).get("ok", False)),
            required=True,
            detail=service_contract.get("embedder_models", {}),
            failure_code="svc_embedder_models_unreachable",
        ),
        _check_row(
            name="svc.grounding_health",
            ok=bool(service_contract.get("grounding_health", {}).get("ok", False)),
            required=True,
            detail=service_contract.get("grounding_health", {}),
            failure_code="svc_grounding_health_unreachable",
        ),
        _check_row(
            name="svc.hypervisor_statusz",
            ok=bool(service_contract.get("hypervisor_statusz", {}).get("ok", False)),
            required=True,
            detail=service_contract.get("hypervisor_statusz", {}),
            failure_code="svc_hypervisor_statusz_unreachable",
        ),
        _check_row(
            name="svc.popup_health",
            ok=bool(service_contract.get("popup_health", {}).get("ok", False)),
            required=True,
            detail=service_contract.get("popup_health", {}),
            failure_code="svc_popup_health_unreachable",
        ),
    ]
    required_failed = [
        str(item.get("failure_code") or "unknown_failure")
        for item in checks
        if bool(item.get("required", False)) and not bool(item.get("ok", False))
    ]
    ready = len(required_failed) == 0
    payload = {
        "schema_version": 1,
        "ts_utc": _utc_now(),
        "dataroot": str(dataroot),
        "vllm_base_url": str(preflight_base),
        "service_contract": service_contract,
        "db_stability": db_stability,
        "ready": bool(ready),
        "failure_codes": sorted(set(required_failed)),
        "checks": checks,
    }

    out = Path(str(args.output))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {"ok": bool(ready), "output": str(out), "failure_codes": sorted(set(required_failed))},
            sort_keys=True,
        )
    )
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
