"""Vector indexing with SQLite backend."""

from __future__ import annotations

import json
import math
import sqlite3
import urllib.request
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocapture.indexing.manifest import bump_manifest, update_manifest_digest, manifest_path
from autocapture.models.bundles import select_bundle, BundleInfo

class HashEmbedder:
    def __init__(self, dims: int = 384) -> None:
        self.dims = int(dims)

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        for token in re.findall(r"[A-Za-z0-9_]+", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dims
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class LocalEmbedder:
    def __init__(self, model_name: str | None = None) -> None:
        self._bundle: BundleInfo | None = None
        if model_name:
            candidate = Path(str(model_name))
            try:
                if candidate.exists():
                    self._bundle = select_bundle("embedder", [candidate])
            except PermissionError:
                self._bundle = None
            except Exception:
                self._bundle = None
        if self._bundle is None:
            self._bundle = select_bundle("embedder")
        dims = 384
        if self._bundle is not None:
            dims = int(self._bundle.config.get("dims", dims))
        self._fallback = HashEmbedder(dims=dims)
        self._model_name = model_name

    def embed(self, text: str) -> list[float]:
        return self._fallback.embed(text)

    def identity(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"backend": "hash", "dims": self._fallback.dims}
        if self._bundle is not None:
            payload.update(
                {
                    "bundle_id": self._bundle.bundle_id,
                    "bundle_version": self._bundle.version,
                    "bundle_path": str(self._bundle.path),
                }
            )
        return payload


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
        self._identity_cache: dict[str, Any] | None = None
        self._identity_mtime: float | None = None
        self._manifest_mtime: float | None = None

    def index(self, doc_id: str, text: str) -> None:
        vec = self._embedder.embed(text)
        self._conn.execute("REPLACE INTO vectors (doc_id, vector) VALUES (?, ?)", (doc_id, json.dumps(vec)))
        self._conn.commit()
        try:
            bump_manifest(self.path, "vector")
        except Exception:
            pass

    def count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM vectors")
        row = cur.fetchone()
        return int(row[0]) if row else 0

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

    def export_json(self, path: str | Path) -> dict[str, Any]:
        cur = self._conn.execute("SELECT doc_id, vector FROM vectors")
        rows = [(str(doc_id), json.loads(vec_json)) for doc_id, vec_json in cur.fetchall()]
        rows.sort(key=lambda item: item[0])
        vectors = [vec for _doc, vec in rows]
        doc_ids = [doc_id for doc_id, _vec in rows]
        scale, quantized = _quantize_vectors(vectors)
        payload = {
            "schema_version": 1,
            "dims": len(vectors[0]) if vectors else 0,
            "scale": scale,
            "doc_ids": doc_ids,
            "vectors": quantized,
        }
        Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    def import_json(self, path: str | Path) -> None:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        scale = float(payload.get("scale", 1.0) or 1.0)
        doc_ids = payload.get("doc_ids", [])
        vectors = payload.get("vectors", [])
        for doc_id, quant in zip(doc_ids, vectors, strict=False):
            vec = _dequantize_vector(quant, scale)
            self._conn.execute("REPLACE INTO vectors (doc_id, vector) VALUES (?, ?)", (doc_id, json.dumps(vec)))
        self._conn.commit()

    def identity(self) -> dict[str, Any]:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            mtime = None
        try:
            manifest_mtime = manifest_path(self.path).stat().st_mtime
        except FileNotFoundError:
            manifest_mtime = None
        if (
            self._identity_cache is None
            or self._identity_mtime != mtime
            or self._manifest_mtime != manifest_mtime
        ):
            digest = None
            if self.path.exists():
                from autocapture_nx.kernel.hashing import sha256_file

                digest = sha256_file(self.path)
            manifest = update_manifest_digest(self.path, "vector", digest)
            self._identity_cache = {
                "backend": "sqlite",
                "path": str(self.path),
                "digest": digest,
                "version": int(manifest.version),
                "manifest_path": str(manifest_path(self.path)),
                "embedder": self._embedder.identity(),
            }
            self._identity_mtime = mtime
            self._manifest_mtime = manifest_mtime
        return dict(self._identity_cache)


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

    def identity(self) -> dict[str, Any]:
        return {
            "backend": "qdrant",
            "url": self.url,
            "collection": self.collection,
            "version": None,
            "digest": None,
            "embedder": self._embedder.identity(),
        }


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


def _quantize_vectors(vectors: list[list[float]]) -> tuple[float, list[list[int]]]:
    max_abs = 0.0
    for vec in vectors:
        for value in vec:
            max_abs = max(max_abs, abs(float(value)))
    scale = (max_abs / 32767.0) if max_abs > 0 else 1.0
    if scale <= 0:
        scale = 1.0
    quantized: list[list[int]] = []
    for vec in vectors:
        row = []
        for value in vec:
            quant = int(round(float(value) / scale))
            if quant > 32767:
                quant = 32767
            if quant < -32767:
                quant = -32767
            row.append(quant)
        quantized.append(row)
    return scale, quantized


def _dequantize_vector(values: list[Any], scale: float) -> list[float]:
    return [float(int(v)) * float(scale) for v in values]


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
