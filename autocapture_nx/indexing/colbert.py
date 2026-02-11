"""Late-interaction (ColBERT-style) indexing utilities.

This module provides a deterministic hash-based fallback embedder so the
pipeline can run without heavyweight dependencies. When a real token embedder
is available (eg Nemotron CoLEmbed v2), a plugin can swap it in while reusing
the same store + rerank path.

Design goals:
- Append-only: do not delete or overwrite existing embeddings.
- Loopback-only network: any real inference should run in localhost servers or
  explicit PyTorch CUDA plugins (outside the scope of this module).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from autocapture_nx.kernel.hashing import sha256_text


def _utc_ts() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def simple_tokenize(text: str, *, max_tokens: int = 192) -> list[str]:
    # Cheap, deterministic tokenization. Real models can override this.
    raw = str(text or "")
    out: list[str] = []
    token = ""
    for ch in raw:
        if ch.isalnum() or ch in {"_", "-"}:
            token += ch
            continue
        if token:
            out.append(token.lower())
            token = ""
            if len(out) >= int(max_tokens):
                break
    if token and len(out) < int(max_tokens):
        out.append(token.lower())
    return out


@dataclass(frozen=True)
class TokenEmbeddings:
    tokens: list[str]
    vectors_f16: bytes  # packed float16 row-major, shape=(len(tokens), dim)
    dim: int
    dtype: str = "f16"


class HashTokenEmbedder:
    def __init__(self, *, dim: int = 32, seed: str = "colbert.hash.v1") -> None:
        self.dim = int(max(8, dim))
        self._seed = str(seed)
        self._digest = sha256_text(json.dumps({"seed": self._seed, "dim": self.dim}, sort_keys=True))[:16]

    def identity(self) -> dict[str, Any]:
        return {"embedder_id": "colbert.hash", "embedder_digest": self._digest, "dim": self.dim, "dtype": "f16"}

    def embed_tokens(self, text: str) -> TokenEmbeddings:
        toks = simple_tokenize(text)
        if not toks:
            return TokenEmbeddings(tokens=[], vectors_f16=b"", dim=self.dim)
        # Build deterministic unit vectors for each token (approx).
        mat = np.zeros((len(toks), self.dim), dtype=np.float32)
        for i, tok in enumerate(toks):
            h = hashlib.sha256((self._seed + "\n" + tok).encode("utf-8")).digest()
            # Fill floats by mapping bytes -> [-1, 1]
            for j in range(self.dim):
                mat[i, j] = (h[j % len(h)] / 127.5) - 1.0
        # L2 normalize rows
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        mat = mat / norms
        return TokenEmbeddings(tokens=toks, vectors_f16=mat.astype(np.float16).tobytes(order="C"), dim=self.dim)

    def embed_query_tokens(self, text: str) -> np.ndarray:
        emb = self.embed_tokens(text)
        if not emb.tokens:
            return np.zeros((0, self.dim), dtype=np.float32)
        mat = np.frombuffer(emb.vectors_f16, dtype=np.float16).reshape((-1, self.dim)).astype(np.float32)
        return mat


def _data_dir() -> Path:
    raw = os.getenv("AUTOCAPTURE_DATA_DIR", "").strip()
    return Path(raw).expanduser().absolute() if raw else Path("data").absolute()


def default_colbert_db_path() -> Path:
    return _data_dir() / "indexes" / "colbert.sqlite3"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS colbert_doc (
  doc_key TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  embedder_id TEXT NOT NULL,
  embedder_digest TEXT NOT NULL,
  text_sha256 TEXT NOT NULL,
  token_count INTEGER NOT NULL,
  dim INTEGER NOT NULL,
  dtype TEXT NOT NULL,
  z_blob BLOB NOT NULL,
  created_ts_utc TEXT NOT NULL,
  provenance_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_colbert_doc_id ON colbert_doc(doc_id);
CREATE INDEX IF NOT EXISTS idx_colbert_doc_embedder ON colbert_doc(embedder_digest);
"""


class ColbertSQLiteStore:
    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def _ensure(self) -> None:
        if self._conn is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def insert_doc(
        self,
        *,
        doc_id: str,
        embedder_identity: dict[str, Any],
        embeddings: TokenEmbeddings,
        text_sha256: str,
        provenance: dict[str, Any] | None = None,
    ) -> bool:
        self._ensure()
        if self._conn is None:
            return False
        embedder_id = str(embedder_identity.get("embedder_id") or "colbert.unknown")
        embedder_digest = str(embedder_identity.get("embedder_digest") or "")
        dim = int(embedder_identity.get("dim") or embeddings.dim or 0)
        dtype = str(embedder_identity.get("dtype") or embeddings.dtype or "f16")
        doc_key = sha256_text(f"{doc_id}\n{embedder_digest}")[:24]
        prov = provenance or {}
        payload = (
            doc_key,
            str(doc_id),
            embedder_id,
            embedder_digest,
            str(text_sha256),
            int(len(embeddings.tokens)),
            int(dim),
            dtype,
            sqlite3.Binary(embeddings.vectors_f16),
            _utc_ts(),
            json.dumps(prov, sort_keys=True),
        )
        try:
            self._conn.execute(
                """
                INSERT INTO colbert_doc (
                  doc_key, doc_id, embedder_id, embedder_digest, text_sha256,
                  token_count, dim, dtype, z_blob, created_ts_utc, provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_docs(self, *, doc_ids: Iterable[str], embedder_digest: str) -> dict[str, dict[str, Any]]:
        self._ensure()
        if self._conn is None:
            return {}
        ids = [str(d) for d in doc_ids if str(d).strip()]
        if not ids:
            return {}
        placeholders = ",".join(["?"] * len(ids))
        rows = self._conn.execute(
            f"""
            SELECT doc_id, token_count, dim, dtype, z_blob, text_sha256
            FROM colbert_doc
            WHERE embedder_digest = ? AND doc_id IN ({placeholders})
            """,
            [str(embedder_digest), *ids],
        ).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for doc_id, token_count, dim, dtype, z_blob, text_sha in rows:
            out[str(doc_id)] = {
                "doc_id": str(doc_id),
                "token_count": int(token_count or 0),
                "dim": int(dim or 0),
                "dtype": str(dtype or ""),
                "blob": bytes(z_blob) if z_blob is not None else b"",
                "text_sha256": str(text_sha or ""),
            }
        return out


def maxsim_score(query_tokens: np.ndarray, doc_tokens_f16: bytes, *, dim: int) -> float:
    if query_tokens.size == 0 or not doc_tokens_f16 or dim <= 0:
        return 0.0
    try:
        doc = np.frombuffer(doc_tokens_f16, dtype=np.float16).reshape((-1, int(dim))).astype(np.float32)
    except Exception:
        return 0.0
    if doc.size == 0:
        return 0.0
    # Normalize rows (defensive).
    q = query_tokens
    qn = np.linalg.norm(q, axis=1, keepdims=True)
    qn[qn == 0.0] = 1.0
    q = q / qn
    dn = np.linalg.norm(doc, axis=1, keepdims=True)
    dn[dn == 0.0] = 1.0
    doc = doc / dn
    # MaxSim late interaction: sum over query tokens of max dot over doc tokens.
    sims = q @ doc.T
    mx = sims.max(axis=1) if sims.size else np.zeros((q.shape[0],), dtype=np.float32)
    return float(mx.sum())
