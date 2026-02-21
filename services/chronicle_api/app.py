from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException

from autocapture_prime.config import PrimeConfig, load_prime_config
from autocapture_prime.eval.metrics import record_qa_metric
from autocapture_prime.ingest.pipeline import ingest_one_session
from autocapture_prime.ingest.session_scanner import SessionScanner


def _state_db(storage_root: Path) -> Path:
    return storage_root / "ingest_state.db"


def create_app(config_path: str | Path | None = None) -> FastAPI:
    cfg = load_prime_config(config_path)
    app = FastAPI(title="chronicle_api", version="0.1.0")
    scanner = SessionScanner(cfg.spool_root, _state_db(cfg.storage_root))

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "service": "chronicle_api"}

    @app.get("/sessions")
    def sessions() -> dict[str, Any]:
        complete = scanner.list_complete()
        pending = scanner.list_pending()
        return {
            "ok": True,
            "complete_count": len(complete),
            "pending_count": len(pending),
            "sessions": [item.session_id for item in complete],
        }

    @app.get("/sessions/{session_id}")
    def session_details(session_id: str) -> dict[str, Any]:
        path = cfg.storage_root / session_id
        if not path.exists():
            raise HTTPException(status_code=404, detail="session not found")
        tables = sorted([p.name for p in path.glob("*") if p.is_file()])
        return {"ok": True, "session_id": session_id, "tables": tables}

    @app.post("/ingest/scan")
    def ingest_scan() -> dict[str, Any]:
        summaries: list[dict[str, Any]] = []
        for session in scanner.list_pending():
            summary = ingest_one_session(session, cfg)
            scanner.mark_processed(session)
            summaries.append(summary)
        return {"ok": True, "processed": len(summaries), "summaries": summaries}

    @app.post("/v1/chat/completions")
    def chat_completions(payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        messages = payload.get("messages", [])
        if not isinstance(messages, list) or not messages:
            raise HTTPException(status_code=400, detail="messages required")
        query = ""
        for item in reversed(messages):
            if isinstance(item, dict) and item.get("role") == "user":
                query = str(item.get("content") or "")
                break
        owner = str(cfg.query_owner or "hypervisor").strip().lower()
        if owner != "hypervisor":
            raise HTTPException(
                status_code=503,
                detail=f"query_owner_not_supported:{owner}; expected=hypervisor",
            )
        forward_payload = dict(payload)
        response: dict[str, Any]
        try:
            response = _call_hypervisor_query(cfg, forward_payload)
        except Exception as exc:
            base = str(cfg.hypervisor_base_url).strip()
            path = str(cfg.hypervisor_chat_path).strip()
            raise HTTPException(
                status_code=503,
                detail=f"hypervisor query unavailable: {exc}; endpoint={base.rstrip('/')}/{path.lstrip('/')}",
            ) from exc
        if isinstance(response, dict):
            usage = response.get("usage")
            if not isinstance(usage, dict):
                usage = {}
            usage["chronicle_query_owner"] = owner
            usage["chronicle_retrieval_hits"] = 0
            response["usage"] = usage
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        evidence_order_hash = _evidence_hash([])
        record_qa_metric(
            cfg.storage_root,
            query=query,
            model=str(forward_payload.get("model") or cfg.vllm_model),
            retrieval_hits=0,
            latency_ms=elapsed_ms,
            plugin_path=["chronicle.forward.hypervisor"],
            confidence=0.0,
            feedback_state="unreviewed",
            evidence_order_hash=evidence_order_hash,
        )
        return response

    return app

def _evidence_hash(evidence: list[dict[str, Any]]) -> str:
    import hashlib

    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _call_hypervisor_query(cfg: PrimeConfig, payload: dict[str, Any]) -> dict[str, Any]:
    base = cfg.hypervisor_base_url.rstrip("/")
    path = str(cfg.hypervisor_chat_path or "/v1/chat/completions").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    if not base.startswith("http://127.0.0.1"):
        raise ValueError("hypervisor endpoint must be localhost")
    url = base + path
    headers: dict[str, str] = {}
    api_key = str(cfg.hypervisor_api_key or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    with httpx.Client(timeout=float(cfg.hypervisor_timeout_s)) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        out = resp.json()
    if not isinstance(out, dict):
        raise ValueError("invalid hypervisor response")
    return out


app = create_app()
