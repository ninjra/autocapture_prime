"""Deterministic screen index answerer (screen.answer.v1)."""

from __future__ import annotations

import re
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokens(text: str) -> set[str]:
    return {tok.casefold() for tok in _TOKEN_RE.findall(str(text or "")) if tok}


class ScreenAnswerPlugin(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        self._default_max_claims = max(1, int(cfg.get("default_max_claims") or 3))

    def capabilities(self) -> dict[str, Any]:
        return {"screen.answer.v1": self}

    def answer(self, query: str, indexed: dict[str, Any], *, max_claims: int | None = None) -> dict[str, Any]:
        q = str(query or "").strip()
        payload = indexed if isinstance(indexed, dict) else {}
        chunks = payload.get("chunks", [])
        evidence = payload.get("evidence", [])
        if not isinstance(chunks, list):
            chunks = []
        if not isinstance(evidence, list):
            evidence = []
        evidence_by_id: dict[str, dict[str, Any]] = {}
        for item in evidence:
            if not isinstance(item, dict):
                continue
            eid = str(item.get("evidence_id") or "").strip()
            if eid:
                evidence_by_id[eid] = item

        q_terms = _tokens(q)
        scored: list[tuple[int, str, dict[str, Any]]] = []
        for item in chunks:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            terms = set(str(t).casefold() for t in (item.get("terms") or []) if str(t).strip())
            if not terms:
                terms = _tokens(text)
            score = len(q_terms.intersection(terms)) if q_terms else 0
            if score <= 0:
                continue
            node_id = str(item.get("node_id") or "")
            scored.append((int(score), node_id, item))
        scored.sort(key=lambda row: (-int(row[0]), str(row[1])))

        limit = max(1, int(max_claims if max_claims is not None else self._default_max_claims))
        claims: list[dict[str, Any]] = []
        for _score, _node_id, item in scored[:limit]:
            text = str(item.get("text") or "").strip()
            evidence_id = str(item.get("evidence_id") or "").strip()
            evidence_obj = evidence_by_id.get(evidence_id, {})
            citations: list[dict[str, Any]] = []
            if evidence_id:
                citations.append(
                    {
                        "evidence_id": evidence_id,
                        "hash": str(evidence_obj.get("hash") or ""),
                        "source": evidence_obj.get("source", {}),
                        "bbox": evidence_obj.get("bbox", []),
                    }
                )
            if not text or not citations:
                continue
            claims.append({"text": text, "citations": citations})

        state = "ok" if claims else "no_evidence"
        summary = claims[0]["text"] if claims else ""
        return {
            "state": state,
            "summary": summary,
            "claims": claims,
            "errors": [],
        }


def create_plugin(plugin_id: str, context: PluginContext) -> ScreenAnswerPlugin:
    return ScreenAnswerPlugin(plugin_id, context)
