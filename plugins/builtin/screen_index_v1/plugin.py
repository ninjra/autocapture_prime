"""Deterministic UI graph indexer (screen.index.v1)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _bbox(raw: Any) -> list[int]:
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        try:
            x1, y1, x2, y2 = [int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3])]
            if x2 < x1:
                x1, x2 = x2, x1
            if y2 < y1:
                y1, y2 = y2, y1
            return [max(0, x1), max(0, y1), max(0, x2), max(0, y2)]
        except Exception:
            return [0, 0, 0, 0]
    return [0, 0, 0, 0]


def _terms(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for tok in _TOKEN_RE.findall(str(text or "").casefold()):
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out


def _sha(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _sort_nodes(node: dict[str, Any]) -> tuple[int, int, int, int, str]:
    b = _bbox(node.get("bbox"))
    return (int(b[1]), int(b[0]), int(b[3]), int(b[2]), str(node.get("node_id") or ""))


class ScreenIndexPlugin(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        self._embed = bool(cfg.get("embed", True))

    def capabilities(self) -> dict[str, Any]:
        return {"screen.index.v1": self}

    def index(self, ui_graph: dict[str, Any], *, frame_id: str = "") -> dict[str, Any]:
        graph = ui_graph if isinstance(ui_graph, dict) else {}
        frame = str(frame_id or graph.get("frame_id") or "").strip() or "frame_unknown"
        nodes = graph.get("nodes", [])
        if not isinstance(nodes, list):
            nodes = []
        normalized = [node for node in nodes if isinstance(node, dict)]
        normalized.sort(key=_sort_nodes)
        try:
            embedder = self.context.get_capability("embedder.text")
        except Exception:
            embedder = None

        chunks: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        for node in normalized:
            node_id = str(node.get("node_id") or "").strip() or "node_unknown"
            kind = str(node.get("kind") or "node").strip()
            text = str(node.get("text") or "").strip()
            label = str(node.get("label") or "").strip()
            content = " ".join(part for part in (kind, label, text) if part).strip()
            bbox = _bbox(node.get("bbox"))
            source = {"frame_id": frame, "node_id": node_id}
            evidence_payload = {
                "evidence_id": "",
                "type": "ui_node",
                "source": source,
                "bbox": bbox,
                "hash": "",
            }
            chunk_seed = {"frame_id": frame, "node_id": node_id, "content": content, "bbox": bbox}
            chunk_hash = _sha(chunk_seed)
            chunk_id = f"chunk_{chunk_hash[:16]}"
            evidence_payload["evidence_id"] = f"evidence_{chunk_hash[:16]}"
            evidence_payload["hash"] = _sha(
                {
                    "frame_id": frame,
                    "node_id": node_id,
                    "content": content,
                    "bbox": bbox,
                    "kind": kind,
                }
            )
            embedding: list[float] = []
            if self._embed and embedder is not None and hasattr(embedder, "embed") and callable(getattr(embedder, "embed")):
                try:
                    raw = embedder.embed(content)
                    if isinstance(raw, list):
                        embedding = [float(v) for v in raw]
                except Exception:
                    embedding = []
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "node_id": node_id,
                    "text": content,
                    "terms": _terms(content),
                    "bbox": bbox,
                    "embedding": embedding,
                    "evidence_id": evidence_payload["evidence_id"],
                }
            )
            evidence.append(evidence_payload)

        return {
            "schema_version": 1,
            "frame_id": frame,
            "chunks": chunks,
            "evidence": evidence,
        }


def create_plugin(plugin_id: str, context: PluginContext) -> ScreenIndexPlugin:
    return ScreenIndexPlugin(plugin_id, context)
