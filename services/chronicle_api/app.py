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
from autocapture_prime.store.index import search_lexical_index


def _state_db(storage_root: Path) -> Path:
    return storage_root / "ingest_state.db"


def _session_rows(session_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stem in ("ocr_spans", "elements"):
        parquet = session_root / f"{stem}.parquet"
        ndjson = session_root / f"{stem}.ndjson"
        path = parquet if parquet.exists() else ndjson
        if not path.exists():
            continue
        if path.suffix == ".parquet":
            try:
                import pyarrow.parquet as pq  # type: ignore

                table = pq.read_table(path)
                for row in table.to_pylist():
                    if isinstance(row, dict):
                        row["_source_table"] = path.name
                        rows.append(row)
                continue
            except Exception:
                # Fall back to ndjson readers if parquet unavailable.
                if not ndjson.exists():
                    continue
                path = ndjson
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    row["_source_table"] = path.name
                    rows.append(row)
    return rows


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
        evidence = _retrieve_evidence(cfg, query, top_k=cfg.top_k_frames)
        forward_payload = dict(payload)
        forward_payload.setdefault("model", cfg.vllm_model)
        if evidence:
            extra = "\n\nRetrieved evidence:\n" + "\n".join(
                f"- {item['session_id']}/frame={item['frame_index']}[{item['source_table']}:{item['extractor']}]"
                f" score={item['score']} rank={item['rank']}: {item['text']}"
                for item in evidence
            )
            forward_payload["messages"] = list(messages) + [{"role": "system", "content": extra}]
        try:
            response = _call_vllm(cfg, forward_payload)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"vllm unavailable: {exc}") from exc
        if isinstance(response, dict):
            usage = response.get("usage")
            if not isinstance(usage, dict):
                usage = {}
            usage["chronicle_retrieval_hits"] = len(evidence)
            usage["chronicle_retrieval"] = evidence
            response["usage"] = usage
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        evidence_order_hash = _evidence_hash(evidence)
        record_qa_metric(
            cfg.storage_root,
            query=query,
            model=str(forward_payload.get("model") or cfg.vllm_model),
            retrieval_hits=len(evidence),
            latency_ms=elapsed_ms,
            plugin_path=["chronicle.retrieve.lexical", "chronicle.forward.vllm_localhost"],
            confidence=_confidence_from_evidence(evidence),
            feedback_state="unreviewed",
            evidence_order_hash=evidence_order_hash,
        )
        return response

    return app


def _retrieve_evidence(cfg: PrimeConfig, query: str, top_k: int) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    if not cfg.storage_root.exists():
        return hits
    for session_root in sorted([p for p in cfg.storage_root.iterdir() if p.is_dir()], key=lambda p: p.name):
        rows = _session_rows(session_root)
        if not rows:
            continue
        index_path = session_root / "lexical_index.json"
        selected = search_lexical_index(index_path, rows, query, top_k=top_k)
        for row in selected:
            text = str(row.get("text") or row.get("label") or "").strip()
            if not text:
                continue
            frame_idx = row.get("frame_index")
            hits.append(
                {
                    "session_id": session_root.name,
                    "frame_index": int(frame_idx or 0),
                    "source_table": str(row.get("_source_table") or ""),
                    "extractor": str(row.get("extractor") or ""),
                    "text": text,
                    "score": int(row.get("_score") or 0),
                    "rank": int(row.get("_rank") or 0),
                    "row_idx": int(row.get("_row_idx") or 0),
                }
            )
    hits.sort(
        key=lambda item: (
            -int(item.get("score") or 0),
            str(item.get("session_id") or ""),
            int(item.get("frame_index") or 0),
            int(item.get("row_idx") or 0),
        )
    )
    out: list[dict[str, Any]] = []
    for rank, item in enumerate(hits[: max(1, top_k)], start=1):
        row = dict(item)
        row["rank"] = rank
        out.append(row)
    return out


def _confidence_from_evidence(evidence: list[dict[str, Any]]) -> float:
    if not evidence:
        return 0.0
    top = int(evidence[0].get("score") or 0)
    score = min(1.0, max(0.0, float(top) / 8.0))
    return score


def _evidence_hash(evidence: list[dict[str, Any]]) -> str:
    import hashlib

    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _call_vllm(cfg: PrimeConfig, payload: dict[str, Any]) -> dict[str, Any]:
    base = cfg.vllm_base_url.rstrip("/")
    if not base.startswith("http://127.0.0.1"):
        raise ValueError("vLLM endpoint must be localhost")
    url = base + "/v1/chat/completions"
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        out = resp.json()
    if not isinstance(out, dict):
        raise ValueError("invalid vLLM response")
    return out


app = create_app()
