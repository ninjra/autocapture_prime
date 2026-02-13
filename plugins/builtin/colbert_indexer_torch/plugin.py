"""Torch-backed ColBERT/Nemotron CoLEmbed indexer (optional).

Second-class path: this plugin is optional and disabled by default.
If model/dependencies are unavailable, it no-ops safely and reports diagnostics.
"""

from __future__ import annotations

from typing import Any

from autocapture_nx.indexing.colbert import ColbertSQLiteStore, HashTokenEmbedder, default_colbert_db_path
from autocapture_nx.indexing.colbert import TokenEmbeddings
from autocapture_nx.kernel.hashing import sha256_text
from autocapture_nx.plugin_system.api import PluginBase, PluginContext
from autocapture_nx.storage.facts_ndjson import append_fact_line


def _facts_cfg() -> dict[str, Any]:
    import os
    from pathlib import Path

    data_dir = os.getenv("AUTOCAPTURE_DATA_DIR", "").strip()
    if not data_dir:
        data_dir = "data"
    return {"storage": {"data_dir": str(Path(data_dir).expanduser().absolute())}}


class TorchColbertIndexer(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        db_path = str(cfg.get("db_path") or "").strip()
        self._store = ColbertSQLiteStore(db_path or default_colbert_db_path())
        self._model_id = str(cfg.get("model_id") or "").strip()
        self._dim = int(cfg.get("dim") or 32)
        self._fallback = HashTokenEmbedder(dim=self._dim)
        self._device = str(cfg.get("device") or "cuda").strip()
        self._model = None
        self._tokenizer = None
        self._err: str | None = None
        self._try_load()

    def capabilities(self) -> dict[str, Any]:
        return {"index.postprocess": self}

    def _try_load(self) -> None:
        if not self._model_id:
            self._err = "model_id_missing"
            return
        try:
            import torch  # noqa: F401
            from transformers import AutoModel, AutoTokenizer

            tok = AutoTokenizer.from_pretrained(self._model_id, trust_remote_code=True)
            mdl = AutoModel.from_pretrained(self._model_id, trust_remote_code=True)
            mdl = mdl.to(self._device)
            mdl.eval()
            self._tokenizer = tok
            self._model = mdl
            self._err = None
        except Exception as exc:
            self._model = None
            self._tokenizer = None
            self._err = f"load_failed:{type(exc).__name__}"

    def _torch_embed(self, text: str):  # type: ignore[no-untyped-def]
        if self._model is None or self._tokenizer is None:
            return None
        import numpy as np
        import torch

        toks = self._tokenizer(
            text,
            truncation=True,
            max_length=192,
            return_tensors="pt",
            add_special_tokens=True,
        )
        toks = {k: v.to(self._device) if hasattr(v, "to") else v for k, v in toks.items()}
        with torch.no_grad():
            out = self._model(**toks)
        last_hidden = getattr(out, "last_hidden_state", None)
        if last_hidden is None:
            return None
        vec = last_hidden[0].detach().float().cpu().numpy()
        # Remove special tokens if possible.
        input_ids = toks.get("input_ids")
        tokens = []
        if input_ids is not None:
            ids = input_ids[0].detach().cpu().tolist()
            tokens = self._tokenizer.convert_ids_to_tokens(ids)
        else:
            tokens = [f"t{i}" for i in range(vec.shape[0])]
        # L2 normalize per token vector.
        norms = np.linalg.norm(vec, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        vec = vec / norms
        return tokens, vec.astype(np.float16).tobytes(order="C"), int(vec.shape[1])

    def process_doc(self, doc_id: str, text: str) -> dict[str, Any]:
        did = str(doc_id or "").strip()
        txt = str(text or "")
        if not did or not txt.strip():
            return {"ok": False, "error": "missing_doc_or_text"}
        text_sha = sha256_text(txt)

        embedded = self._torch_embed(txt)
        if embedded is None:
            emb = self._fallback.embed_tokens(txt)
            ident = self._fallback.identity()
            backend = "fallback_hash"
        else:
            tokens, blob, dim = embedded
            emb = TokenEmbeddings(tokens=tokens, vectors_f16=blob, dim=dim)
            ident = {
                "embedder_id": "colbert.torch",
                "embedder_digest": sha256_text(f"{self._model_id}:{dim}:{self._device}")[:16],
                "dim": int(dim),
                "dtype": "f16",
                "model_id": self._model_id,
                "device": self._device,
            }
            backend = "torch"

        inserted = False
        if emb.tokens:
            inserted = self._store.insert_doc(
                doc_id=did,
                embedder_identity=ident,
                embeddings=emb,
                text_sha256=text_sha,
                provenance={"plugin_id": self.plugin_id, "embedder": ident, "backend": backend, "error": self._err},
            )
        payload = {
            "schema_version": 1,
            "record_type": "derived.index.colbert",
            "doc_id": did,
            "embedder_id": ident.get("embedder_id"),
            "embedder_digest": ident.get("embedder_digest"),
            "token_count": int(len(emb.tokens)),
            "dim": int(ident.get("dim") or emb.dim),
            "inserted": bool(inserted),
            "text_sha256": text_sha,
            "backend": backend,
            "error": self._err,
        }
        try:
            _ = append_fact_line(_facts_cfg(), rel_path="colbert_index.ndjson", payload=payload)
        except Exception:
            pass
        return {"ok": True, "inserted": bool(inserted), "token_count": int(len(emb.tokens)), "backend": backend}


def create_plugin(plugin_id: str, context: PluginContext) -> TorchColbertIndexer:
    return TorchColbertIndexer(plugin_id, context)
