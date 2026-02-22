"""Query route."""

from __future__ import annotations

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
def query_popup(req: PopupQueryRequest, request: Request):
    _ = req.schedule_extract
    result = request.app.state.facade.query(req.query, schedule_extract=False)
    if not isinstance(result, dict):
        return {
            "ok": False,
            "query": str(req.query),
            "error": "invalid_query_result",
            "summary": "",
            "bullets": [],
            "citations": [],
        }
    return _popup_payload(str(req.query), result, int(req.max_citations))


@router.post("/api/state/query")
def state_query(req: QueryRequest, request: Request):
    return request.app.state.facade.state_query(req.query)
