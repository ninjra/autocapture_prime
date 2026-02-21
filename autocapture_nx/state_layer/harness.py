"""Deterministic evaluation harness for state-layer retrieval."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from autocapture_nx.plugin_system.api import PluginContext

from .builder_jepa import JEPAStateBuilder
from .retrieval import StateRetrieval
from .store_sqlite import StateTapeStore


@dataclass(frozen=True)
class StateEvalCase:
    case_id: str
    query: str
    expected_state_ids: list[str] = field(default_factory=list)
    expected_span_indices: list[int] = field(default_factory=list)
    min_recall: float = 1.0
    min_precision: float = 0.34
    top_k: int = 3
    time_window: dict[str, Any] | None = None


def _parse_cases(cases: Iterable[dict[str, Any]]) -> list[StateEvalCase]:
    parsed: list[StateEvalCase] = []
    seen: set[str] = set()
    for idx, raw in enumerate(cases):
        if not isinstance(raw, dict):
            raise ValueError(f"case {idx} must be an object")
        case_id = str(raw.get("id") or raw.get("case_id") or "").strip()
        if not case_id:
            raise ValueError(f"case {idx} missing id")
        if case_id in seen:
            raise ValueError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        parsed.append(
            StateEvalCase(
                case_id=case_id,
                query=str(raw.get("query") or ""),
                expected_state_ids=list(raw.get("expected_state_ids") or []),
                expected_span_indices=list(raw.get("expected_span_indices") or []),
                min_recall=float(raw.get("min_recall", 1.0)),
                min_precision=float(raw.get("min_precision", 0.34)),
                top_k=int(raw.get("top_k", 3)),
                time_window=raw.get("time_window") if isinstance(raw.get("time_window"), dict) else None,
            )
        )
    return parsed


def load_state_eval_cases(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("state eval fixture must be an object with keys: states, cases")
    cases_raw = payload.get("cases") or []
    if not isinstance(cases_raw, list):
        raise ValueError("state eval cases must be a list")
    states = payload.get("states") or []
    if not isinstance(states, list):
        raise ValueError("state eval states must be a list")
    return {"states": states, "cases": _parse_cases(cases_raw)}


def _build_state_tape(
    config: dict[str, Any],
    states: list[dict[str, Any]],
    *,
    session_id: str = "run",
    path: Path,
) -> tuple[StateTapeStore, list[dict[str, Any]], list[dict[str, Any]]]:
    ctx = PluginContext(
        config=config,
        get_capability=lambda _name: None,
        logger=lambda *_args, **_kwargs: None,
        rng=None,
        rng_seed=None,
        rng_seed_hex=None,
    )
    builder = JEPAStateBuilder("state.eval.builder", ctx)
    batch = {"session_id": session_id, "states": list(states)}
    output = builder.process(batch)
    spans = list(output.get("spans") or [])
    edges = list(output.get("edges") or [])
    store = StateTapeStore(path)
    store.insert_batch(spans, edges)
    return store, spans, edges


def run_state_eval(
    config: dict[str, Any],
    *,
    cases: Iterable[StateEvalCase],
    states: list[dict[str, Any]] | None = None,
    state_db_path: str | Path | None = None,
) -> dict[str, Any]:
    cases_list = list(cases)
    spans: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if state_db_path is None:
        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / "state_eval.db"
    else:
        db_path = Path(state_db_path)
    if states is not None:
        store, spans, edges = _build_state_tape(config, states, path=db_path)
    else:
        store = StateTapeStore(db_path)
    ctx = PluginContext(
        config=config,
        get_capability=lambda name: store if name == "storage.state_tape" else None,
        logger=lambda *_args, **_kwargs: None,
        rng=None,
        rng_seed=None,
        rng_seed_hex=None,
    )
    retrieval = StateRetrieval("state.eval.retrieval", ctx)

    results: list[dict[str, Any]] = []
    failed = 0
    for case in cases_list:
        expected_ids = list(case.expected_state_ids)
        if not expected_ids and case.expected_span_indices and spans:
            for idx in case.expected_span_indices:
                try:
                    expected_ids.append(str(spans[int(idx)]["state_id"]))
                except Exception:
                    continue
        hits = retrieval.search(case.query, time_window=case.time_window, limit=case.top_k)
        hit_ids = [str(hit.get("state_id")) for hit in hits if hit.get("state_id")]
        expected = set(expected_ids)
        hits_found = expected.intersection(hit_ids) if expected else set()
        precision = len(hits_found) / max(1, len(hit_ids))
        recall = len(hits_found) / max(1, len(expected))
        ok = precision >= case.min_precision and recall >= case.min_recall
        if not ok:
            failed += 1
        results.append(
            {
                "case_id": case.case_id,
                "query": case.query,
                "expected_state_ids": expected_ids,
                "hit_state_ids": hit_ids,
                "precision": precision,
                "recall": recall,
                "ok": ok,
            }
        )
    summary = {
        "ok": failed == 0,
        "total": len(results),
        "failed": failed,
        "cases": results,
    }
    if temp_dir is not None:
        temp_dir.cleanup()
    return summary
