"""Vector indexing with SQLite backend."""

from __future__ import annotations

import json
import math
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class HashEmbedder:
    def __init__(self, dims: int = 64) -> None:
        self.dims = dims

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        for token in text.lower().split():
            idx = hash(token) % self.dims
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class LocalEmbedder:
    def __init__(self, model_name: str | None = None) -> None:
        self._model = None
        self._fallback = HashEmbedder()
        if model_name:
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(model_name)
            except Exception:
                self._model = None

    def embed(self, text: str) -> list[float]:
        if self._model is None:
            return self._fallback.embed(text)
        embedding = self._model.encode([text])[0]
        return [float(v) for v in embedding]


class QdrantSidecar:
    def __init__(self, url: str, health_path: str = "/healthz", binary_path: str | None = None) -> None:
        self.url = url.rstrip("/")
        self.health_path = health_path
        self.binary_path = Path(binary_path) if binary_path else None

    def healthcheck(self) -> dict[str, Any]:
        if self.binary_path and not self.binary_path.exists():
            return {"ok": False, "reason": "binary_missing", "path": str(self.binary_path)}
        try:
            with urllib.request.urlopen(f"{self.url}{self.health_path}", timeout=2.0) as resp:
                return {"ok": resp.status == 200, "status_code": resp.status}
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}


def _request_json(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


@dataclass
class VectorHit:
    doc_id: str
    score: float


class VectorIndex:
    def __init__(self, path: str | Path, embedder: LocalEmbedder) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("CREATE TABLE IF NOT EXISTS vectors (doc_id TEXT PRIMARY KEY, vector TEXT)")
        self._conn.commit()
        self._embedder = embedder

    def index(self, doc_id: str, text: str) -> None:
        vec = self._embedder.embed(text)
        self._conn.execute("REPLACE INTO vectors (doc_id, vector) VALUES (?, ?)", (doc_id, json.dumps(vec)))
        self._conn.commit()

    def query(self, text: str, limit: int = 5) -> list[VectorHit]:
        query_vec = self._embedder.embed(text)
        cur = self._conn.execute("SELECT doc_id, vector FROM vectors")
        hits: list[VectorHit] = []
        for doc_id, vec_json in cur.fetchall():
            vec = json.loads(vec_json)
            score = _cosine(query_vec, vec)
            hits.append(VectorHit(doc_id=doc_id, score=score))
        hits.sort(key=lambda h: (-h.score, h.doc_id))
        return hits[:limit]


class QdrantVectorIndex:
    def __init__(self, url: str, collection: str, embedder: LocalEmbedder) -> None:
        self.url = url.rstrip("/")
        self.collection = collection
        self._embedder = embedder
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        try:
            _request_json("GET", f"{self.url}/collections/{self.collection}")
            return
        except Exception:
            pass
        dims = len(self._embedder.embed("dimension_probe"))
        payload = {"vectors": {"size": dims, "distance": "Cosine"}}
        _request_json("PUT", f"{self.url}/collections/{self.collection}", payload)

    def index(self, doc_id: str, text: str) -> None:
        vec = self._embedder.embed(text)
        payload = {"points": [{"id": doc_id, "vector": vec, "payload": {"text": text}}]}
        _request_json("PUT", f"{self.url}/collections/{self.collection}/points?wait=true", payload)

    def query(self, text: str, limit: int = 5) -> list[VectorHit]:
        query_vec = self._embedder.embed(text)
        payload = {"vector": query_vec, "limit": limit}
        result = _request_json("POST", f"{self.url}/collections/{self.collection}/points/search", payload)
        hits: list[VectorHit] = []
        for item in result.get("result", []) or []:
            hits.append(VectorHit(doc_id=str(item.get("id")), score=float(item.get("score", 0.0))))
        hits.sort(key=lambda h: (-h.score, h.doc_id))
        return hits[:limit]


def create_vector_backend(plugin_id: str) -> VectorIndex:
    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config

    config = load_config(default_config_paths(), safe_mode=False)
    path = config.get("storage", {}).get("vector_path", "data/vector.db")
    model_name = config.get("indexing", {}).get("embedder_model")
    backend = config.get("indexing", {}).get("vector_backend", "sqlite")
    if backend == "qdrant":
        qcfg = config.get("indexing", {}).get("qdrant", {})
        url = qcfg.get("url", "http://localhost:6333")
        collection = qcfg.get("collection", "autocapture")
        return QdrantVectorIndex(url, collection, LocalEmbedder(model_name))
    return VectorIndex(path, LocalEmbedder(model_name))


def create_embedder(plugin_id: str) -> LocalEmbedder:
    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config

    config = load_config(default_config_paths(), safe_mode=False)
    model_name = config.get("indexing", {}).get("embedder_model")
    return LocalEmbedder(model_name)


def qdrant_healthcheck() -> dict[str, Any]:
    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config

    config = load_config(default_config_paths(), safe_mode=False)
    backend = config.get("indexing", {}).get("vector_backend", "sqlite")
    if backend != "qdrant":
        return {"ok": True, "skipped": True, "reason": "disabled"}
    qcfg = config.get("indexing", {}).get("qdrant", {})
    sidecar = QdrantSidecar(
        qcfg.get("url", "http://localhost:6333"),
        qcfg.get("health_path", "/healthz"),
        qcfg.get("binary_path"),
    )
    result = sidecar.healthcheck()
    result["skipped"] = False
    return result
