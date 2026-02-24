"""Query route."""

from __future__ import annotations

import asyncio
import os
import time
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Any

router = APIRouter()


class QueryRequest(BaseModel):
    query: str
    schedule_extract: bool = False


class PopupQueryRequest(BaseModel):
    query: str
    schedule_extract: bool = False
    max_citations: int = 8


_POPUP_FORBIDDEN_BLOCK_REASON = "query_compute_disabled"
_POPUP_FORBIDDEN_STATE = "not_available_yet"
_POPUP_TIMEOUT_REASON = "popup_timeout"


def _popup_timeout_seconds() -> float:
    raw = str(os.environ.get("AUTOCAPTURE_POPUP_QUERY_TIMEOUT_S") or "").strip()
    try:
        value = float(raw) if raw else 6.0
    except Exception:
        value = 6.0
    return float(max(1.0, min(30.0, value)))


def _popup_timeout_result(query: str, timeout_s: float) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "popup_query_timeout",
        "answer": {
            "state": "degraded",
            "summary": "Popup query timed out before corpus retrieval completed.",
            "display": {
                "summary": "Popup query timed out before corpus retrieval completed.",
                "bullets": [
                    "Popup query timed out; retry once services are responsive.",
                    "No extraction was scheduled from popup mode.",
                ],
                "topic": "runtime",
            },
            "claims": [],
        },
        "processing": {
            "extraction": {"blocked": True, "blocked_reason": _POPUP_TIMEOUT_REASON, "scheduled_extract_job_id": ""},
            "query_trace": {
                "query_run_id": f"qry_popup_timeout_{uuid4().hex[:12]}",
                "stage_ms": {"total": float(max(0.0, timeout_s) * 1000.0)},
            },
        },
    }


def _popup_error_result(query: str, error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": str(error or "popup_query_failed"),
        "answer": {
            "state": "degraded",
            "summary": "Popup query failed before a corpus-backed answer was available.",
            "display": {
                "summary": "Popup query failed before a corpus-backed answer was available.",
                "bullets": [
                    "Runtime exception in popup query path.",
                    "No extraction was scheduled from popup mode.",
                ],
                "topic": "runtime",
            },
            "claims": [],
        },
        "processing": {
            "extraction": {"blocked": True, "blocked_reason": "popup_query_failed", "scheduled_extract_job_id": ""},
            "query_trace": {
                "query_run_id": f"qry_popup_error_{uuid4().hex[:12]}",
                "stage_ms": {"total": 0.0},
            },
        },
    }


def _compact_citations(result: dict[str, Any], max_items: int) -> list[dict[str, Any]]:
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    claims = answer.get("claims", []) if isinstance(answer.get("claims", []), list) else []
    out: list[dict[str, Any]] = []
    limit = max(1, min(int(max_items or 0), 32))
    for claim_index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue
        claim_text = str(claim.get("text") or "").strip()
        citations = claim.get("citations", []) if isinstance(claim.get("citations", []), list) else []
        for citation_index, citation in enumerate(citations):
            if not isinstance(citation, dict):
                continue
            out.append(
                {
                    "claim_index": int(claim_index),
                    "citation_index": int(citation_index),
                    "claim_text": claim_text,
                    "record_id": str(citation.get("record_id") or ""),
                    "record_type": str(citation.get("record_type") or ""),
                    "source": str(citation.get("source") or ""),
                    "span_kind": str(citation.get("span_kind") or ""),
                    "offset_start": int(citation.get("offset_start") or 0),
                    "offset_end": int(citation.get("offset_end") or 0),
                    "stale": bool(citation.get("stale", False)),
                    "stale_reason": str(citation.get("stale_reason") or ""),
                }
            )
            if len(out) >= limit:
                return out
    return out


def _popup_has_corpus_hits(result: dict[str, Any]) -> bool:
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    claims = answer.get("claims", []) if isinstance(answer.get("claims", []), list) else []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        citations = claim.get("citations", []) if isinstance(claim.get("citations", []), list) else []
        if citations:
            return True
    return False


def _popup_payload(query: str, result: dict[str, Any], max_citations: int) -> dict[str, Any]:
    answer = result.get("answer", {}) if isinstance(result.get("answer", {}), dict) else {}
    display = answer.get("display", {}) if isinstance(answer.get("display", {}), dict) else {}
    processing = result.get("processing", {}) if isinstance(result.get("processing", {}), dict) else {}
    extraction = processing.get("extraction", {}) if isinstance(processing.get("extraction", {}), dict) else {}
    trace = processing.get("query_trace", {}) if isinstance(processing.get("query_trace", {}), dict) else {}
    stage_ms = trace.get("stage_ms", {}) if isinstance(trace.get("stage_ms", {}), dict) else {}
    summary = str(display.get("summary") or answer.get("summary") or "").strip()
    bullets_raw = display.get("bullets", []) if isinstance(display.get("bullets", []), list) else []
    bullets = [str(item).strip() for item in bullets_raw if str(item).strip()]
    confidence_raw = display.get("confidence_pct", answer.get("confidence", None))
    confidence_pct: float | None = None
    try:
        if confidence_raw is not None:
            value = float(confidence_raw)
            confidence_pct = value * 100.0 if 0.0 <= value <= 1.0 else value
    except Exception:
        confidence_pct = None
    state = str(answer.get("state") or "")
    blocked_reason = str(extraction.get("blocked_reason") or "")
    requires_processing = bool(extraction.get("blocked", False))
    # Guard popup contract: once corpus-backed claims exist, response must not
    # degrade into upstream "not available" placeholders.
    if _popup_has_corpus_hits(result) and (
        state.strip().casefold() == _POPUP_FORBIDDEN_STATE
        or blocked_reason.strip().casefold() == _POPUP_FORBIDDEN_BLOCK_REASON
    ):
        state = "ok"
        blocked_reason = ""
        requires_processing = False
    return {
        "ok": bool(result.get("ok", True)),
        "query": str(query),
        "query_run_id": str(trace.get("query_run_id") or ""),
        "state": state,
        "summary": summary,
        "bullets": bullets,
        "topic": str(display.get("topic") or ""),
        "confidence_pct": confidence_pct,
        "needs_processing": requires_processing,
        "processing_blocked_reason": blocked_reason,
        "scheduled_extract_job_id": str(result.get("scheduled_extract_job_id") or extraction.get("scheduled_extract_job_id") or ""),
        "latency_ms_total": float(stage_ms.get("total") or 0.0),
        "citations": _compact_citations(result, max_items=max_citations),
    }


@router.post("/api/query")
def query(req: QueryRequest, request: Request):
    _ = req.schedule_extract
    return request.app.state.facade.query(req.query, schedule_extract=False)


@router.post("/api/query/popup")
async def query_popup(req: PopupQueryRequest, request: Request):
    _ = req.schedule_extract
    timeout_s = _popup_timeout_seconds()
    started = time.perf_counter()
    try:
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: request.app.state.facade.query(req.query, schedule_extract=False),
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        result = _popup_timeout_result(str(req.query), timeout_s)
    except Exception as exc:
        result = _popup_error_result(str(req.query), f"{type(exc).__name__}:{exc}")
    if not isinstance(result, dict):
        return {
            "ok": False,
            "query": str(req.query),
            "error": "invalid_query_result",
            "summary": "",
            "bullets": [],
            "citations": [],
        }
    payload = _popup_payload(str(req.query), result, int(req.max_citations))
    try:
        total_ms = float(payload.get("latency_ms_total") or 0.0)
    except Exception:
        total_ms = 0.0
    if total_ms <= 0.0:
        payload["latency_ms_total"] = round((time.perf_counter() - started) * 1000.0, 3)
    return payload


@router.post("/api/state/query")
def state_query(req: QueryRequest, request: Request):
    return request.app.state.facade.state_query(req.query)
