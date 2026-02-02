"""JEPA training and approved inference gate (optional)."""

from __future__ import annotations

import hmac
import json
import os
import time
from pathlib import Path
import shutil
from typing import Any

from autocapture_nx.kernel.audit import append_audit_event
from autocapture_nx.kernel.canonical_json import dumps as canonical_dumps
from autocapture_nx.kernel.hashing import sha256_text
from autocapture_nx.kernel.paths import resolve_repo_path
from autocapture_nx.plugin_system.api import PluginBase, PluginContext

from .harness import load_state_eval_cases, run_state_eval
from .ids import compute_config_hash, compute_embedding_hash, deterministic_id_from_parts
from .jepa_model import train_model


class JEPATraining(PluginBase):
    VERSION = "0.1.0"

    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        state_cfg = cfg.get("processing", {}).get("state_layer", {}) if isinstance(cfg.get("processing", {}), dict) else {}
        builder_cfg = state_cfg.get("builder", {}) if isinstance(state_cfg.get("builder", {}), dict) else {}
        training_cfg = state_cfg.get("training", {}) if isinstance(state_cfg.get("training", {}), dict) else {}
        self._config_hash = compute_config_hash(builder_cfg)
        data_dir = cfg.get("storage", {}).get("data_dir", "data")
        self._root = Path(str(data_dir)) / "state" / "models" / "jepa"
        self._root.mkdir(parents=True, exist_ok=True)
        self._key_path = self._root / "signing.key"
        self._approvals_path = self._root / "approvals.json"
        self._auto_approve = bool(training_cfg.get("auto_approve", False))
        self._training_cfg = training_cfg
        self._retention_cfg = training_cfg.get("retention", {}) if isinstance(training_cfg.get("retention", {}), dict) else {}

    def capabilities(self) -> dict[str, Any]:
        return {"state.training": self}

    def train(self, dataset: dict[str, Any]) -> dict[str, Any]:
        payload = dataset if isinstance(dataset, dict) else {}
        spans = payload.get("spans", [])
        edges = payload.get("edges", [])
        evidence = payload.get("evidence", [])
        features = _features_from_spans(spans)
        if len(features) < 2:
            return {"status": "failed", "reason": "insufficient_features"}
        dataset_hash = _dataset_fingerprint(spans, edges, evidence)
        model_version = f"jepa-{dataset_hash[:12]}"
        training_run_id = deterministic_id_from_parts(
            {
                "kind": "jepa_training",
                "plugin_id": self.plugin_id,
                "plugin_version": self.VERSION,
                "config_hash": self._config_hash,
                "dataset_hash": dataset_hash,
            }
        )
        created_ts_ms = int(time.time() * 1000)
        model_dir = self._model_dir(model_version, training_run_id)
        model_dir.mkdir(parents=True, exist_ok=True)
        eval_summary = _sanitize_eval(self._run_golden_eval())
        model, report = train_model(
            features,
            model_version=model_version,
            training_run_id=training_run_id,
            config_hash=self._config_hash,
            dataset_hash=dataset_hash,
            training_cfg=self._training_cfg,
            eval_summary=eval_summary if isinstance(eval_summary, dict) else {},
            created_ts_ms=created_ts_ms,
        )
        report_sha256 = sha256_text(canonical_dumps(report))
        record = model.to_payload()
        record.update(
            {
                "spans_count": len(spans) if isinstance(spans, list) else 0,
                "edges_count": len(edges) if isinstance(edges, list) else 0,
                "evidence_count": len(evidence) if isinstance(evidence, list) else 0,
                "config_hash": self._config_hash,
                "producer_plugin_id": self.plugin_id,
                "producer_plugin_version": self.VERSION,
                "report_sha256": report_sha256,
            }
        )
        model_path = model_dir / "model.json"
        model_path.write_text(canonical_dumps(record), encoding="utf-8")
        report_path = model_dir / "report.json"
        report_path.write_text(canonical_dumps(report), encoding="utf-8")
        signature = self._sign_bytes(model_path.read_bytes())
        sig_path = model_dir / "model.sig"
        sig_path.write_text(signature, encoding="utf-8")

        approved = False
        if self._auto_approve and eval_summary.get("ok"):
            self.approve_model(model_version, training_run_id)
            approved = True

        append_audit_event(
            action="state.training.artifact_written",
            actor="state_jepa_training",
            outcome="ok" if eval_summary.get("ok") else "warning",
            details={
                "model_version": model_version,
                "training_run_id": training_run_id,
                "approved": approved,
                "eval_ok": bool(eval_summary.get("ok")),
            },
        )
        try:
            self.archive_models(dry_run=False)
        except Exception:
            pass

        return {
            "status": "ok" if eval_summary.get("ok") else "failed",
            "model_version": model_version,
            "training_run_id": training_run_id,
            "artifact_dir": str(model_dir),
            "signature": signature,
            "approved": approved,
            "eval": eval_summary,
            "report_sha256": report_sha256,
            "report_path": str(report_path),
        }

    def approve_model(self, model_version: str, training_run_id: str) -> dict[str, Any]:
        model_dir = self._model_dir(model_version, training_run_id)
        model_path = model_dir / "model.json"
        sig_path = model_dir / "model.sig"
        if not model_path.exists():
            raise FileNotFoundError("model_not_found")
        if not sig_path.exists():
            raise PermissionError("model_signature_missing")
        payload = json.loads(model_path.read_text(encoding="utf-8"))
        eval_block = payload.get("eval", {}) if isinstance(payload, dict) else {}
        if isinstance(eval_block, dict) and not bool(eval_block.get("ok", False)):
            raise PermissionError("eval_failed")
        signature = sig_path.read_text(encoding="utf-8").strip()
        approvals = self._load_approvals()
        entry = {
            "model_version": model_version,
            "training_run_id": training_run_id,
            "signature": signature,
            "approved_ts_ms": int(time.time() * 1000),
        }
        if not any(
            item.get("model_version") == model_version
            and item.get("training_run_id") == training_run_id
            and item.get("signature") == signature
            for item in approvals
            if isinstance(item, dict)
        ):
            approvals.append(entry)
            self._approvals_path.write_text(canonical_dumps(approvals), encoding="utf-8")
        append_audit_event(
            action="state.training.approved",
            actor="state_jepa_training",
            outcome="ok",
            details={"model_version": model_version, "training_run_id": training_run_id},
        )
        try:
            self.archive_models(dry_run=False)
        except Exception:
            pass
        return {"approved": True, "model_version": model_version, "training_run_id": training_run_id}

    def approve_latest(self, *, include_archived: bool = False) -> dict[str, Any]:
        models = self.list_models(include_archived=include_archived)
        if not models:
            return {"approved": False, "reason": "no_models"}
        candidates = [item for item in models if not item.get("approved")]
        if not candidates:
            return {"approved": False, "reason": "no_unapproved_models"}
        candidates.sort(
            key=lambda item: (
                int(item.get("created_ts_ms", 0) or 0),
                str(item.get("model_version") or ""),
                str(item.get("training_run_id") or ""),
            ),
            reverse=True,
        )
        last_error: str | None = None
        for item in candidates:
            model_version = str(item.get("model_version") or "")
            training_run_id = str(item.get("training_run_id") or "")
            if not model_version or not training_run_id:
                continue
            try:
                return self.approve_model(model_version, training_run_id)
            except Exception as exc:
                last_error = str(exc)
                continue
        return {"approved": False, "reason": "no_approvable_models", "error": last_error}

    def promote_model(self, model_version: str, training_run_id: str) -> dict[str, Any]:
        approvals = self._load_approvals()
        updated = False
        now = int(time.time() * 1000)
        for item in approvals:
            if item.get("model_version") == model_version and item.get("training_run_id") == training_run_id:
                if "initial_approved_ts_ms" not in item:
                    item["initial_approved_ts_ms"] = int(item.get("approved_ts_ms", now) or now)
                item["approved_ts_ms"] = now
                item["promoted_ts_ms"] = now
                updated = True
                break
        if not updated:
            raise FileNotFoundError("approved_model_not_found")
        self._approvals_path.write_text(canonical_dumps(approvals), encoding="utf-8")
        append_audit_event(
            action="state.training.promoted",
            actor="state_jepa_training",
            outcome="ok",
            details={"model_version": model_version, "training_run_id": training_run_id},
        )
        try:
            self.archive_models(dry_run=False)
        except Exception:
            pass
        return {"promoted": True, "model_version": model_version, "training_run_id": training_run_id}

    def latest_approved(self) -> dict[str, Any] | None:
        approvals = self._load_approvals()
        if not approvals:
            return None
        approvals.sort(key=lambda item: int(item.get("approved_ts_ms", 0) or 0), reverse=True)
        return approvals[0]

    def load_latest(self, *, expected_config_hash: str | None = None) -> dict[str, Any] | None:
        latest = self.latest_approved()
        if latest is None:
            return None
        model_version = str(latest.get("model_version") or "")
        training_run_id = str(latest.get("training_run_id") or "")
        if not model_version or not training_run_id:
            return None
        try:
            payload = self.load_model(model_version, training_run_id)
        except Exception:
            return None
        if expected_config_hash and str(payload.get("config_hash") or "") != str(expected_config_hash):
            return None
        return payload

    def load_model(self, model_version: str, training_run_id: str, *, expected_model_version: str | None = None) -> dict[str, Any]:
        model_dir = self._model_dir(model_version, training_run_id)
        model_path = model_dir / "model.json"
        sig_path = model_dir / "model.sig"
        if not model_path.exists():
            archive_path = self._resolve_archive_path(model_version, training_run_id)
            if archive_path is not None:
                model_path = archive_path / "model.json"
                sig_path = archive_path / "model.sig"
            else:
                raise FileNotFoundError("model_not_found")
        if not sig_path.exists():
            raise PermissionError("model_signature_missing")
        payload = json.loads(model_path.read_text(encoding="utf-8"))
        eval_block = payload.get("eval", {}) if isinstance(payload, dict) else {}
        if isinstance(eval_block, dict) and not bool(eval_block.get("ok", False)):
            append_audit_event(
                action="state.training.load",
                actor="state_jepa_training",
                outcome="denied",
                details={"model_version": model_version, "training_run_id": training_run_id, "reason": "eval_failed"},
            )
            raise PermissionError("eval_failed")
        signature = sig_path.read_text(encoding="utf-8").strip()
        if not self._verify_signature(model_path.read_bytes(), signature):
            append_audit_event(
                action="state.training.load",
                actor="state_jepa_training",
                outcome="denied",
                details={"model_version": model_version, "training_run_id": training_run_id, "reason": "signature_mismatch"},
            )
            raise PermissionError("signature_mismatch")
        if expected_model_version and str(payload.get("model_version")) != str(expected_model_version):
            append_audit_event(
                action="state.training.load",
                actor="state_jepa_training",
                outcome="denied",
                details={"model_version": model_version, "training_run_id": training_run_id, "reason": "model_version_mismatch"},
            )
            raise ValueError("model_version_mismatch")
        if not self._is_approved(model_version, training_run_id, signature):
            append_audit_event(
                action="state.training.load",
                actor="state_jepa_training",
                outcome="denied",
                details={"model_version": model_version, "training_run_id": training_run_id, "reason": "unapproved_model"},
            )
            raise PermissionError("model_not_approved")
        append_audit_event(
            action="state.training.load",
            actor="state_jepa_training",
            outcome="ok",
            details={"model_version": model_version, "training_run_id": training_run_id},
        )
        return payload if isinstance(payload, dict) else {}

    def list_models(self, *, include_archived: bool = True) -> list[dict[str, Any]]:
        models: list[dict[str, Any]] = []
        approvals = self._load_approvals()
        approved_index = {
            (item.get("model_version"), item.get("training_run_id")): item
            for item in approvals
            if isinstance(item, dict)
        }
        active = self.latest_approved()
        active_key = None
        if active:
            active_key = (active.get("model_version"), active.get("training_run_id"))
        roots = [self._root]
        if include_archived:
            roots.append(self._archive_root())
        for root in roots:
            if not root.exists():
                continue
            for model_dir in root.glob("*/*"):
                model_path = model_dir / "model.json"
                if not model_path.exists():
                    continue
                try:
                    payload = json.loads(model_path.read_text(encoding="utf-8"))
                except Exception:
                    payload = {}
                model_version = str(payload.get("model_version") or model_dir.parent.name)
                training_run_id = str(payload.get("training_run_id") or model_dir.name)
                report_path = model_dir / "report.json"
                entry = {
                    "model_version": model_version,
                    "training_run_id": training_run_id,
                    "created_ts_ms": int(payload.get("created_ts_ms", 0) or 0),
                    "eval": payload.get("eval", {}) if isinstance(payload.get("eval"), dict) else {},
                    "report_sha256": payload.get("report_sha256"),
                    "path": str(model_dir),
                    "report_available": report_path.exists(),
                    "active": active_key == (model_version, training_run_id),
                }
                approval = approved_index.get((model_version, training_run_id))
                if approval:
                    entry["approved"] = True
                    entry["approved_ts_ms"] = int(approval.get("approved_ts_ms", 0) or 0)
                    entry["archived_ts_ms"] = int(approval.get("archived_ts_ms", 0) or 0) or None
                    entry["archive_path"] = approval.get("archive_path")
                else:
                    entry["approved"] = False
                models.append(entry)
        models.sort(key=lambda item: (-int(item.get("approved_ts_ms", 0) or 0), -int(item.get("created_ts_ms", 0) or 0)))
        return models

    def report(self, model_version: str, training_run_id: str) -> dict[str, Any]:
        model_dir = self._model_dir(model_version, training_run_id)
        report_path = model_dir / "report.json"
        model_path = model_dir / "model.json"
        if not report_path.exists():
            archive_path = self._resolve_archive_path(model_version, training_run_id)
            if archive_path is not None:
                report_path = archive_path / "report.json"
                model_path = archive_path / "model.json"
        if not report_path.exists():
            return {"ok": False, "error": "report_not_found", "model_version": model_version, "training_run_id": training_run_id}
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            return {"ok": False, "error": "report_invalid", "model_version": model_version, "training_run_id": training_run_id}
        if not isinstance(report, dict):
            return {"ok": False, "error": "report_invalid", "model_version": model_version, "training_run_id": training_run_id}
        actual_sha256 = sha256_text(canonical_dumps(report))
        expected_sha256 = None
        integrity_ok = None
        if model_path.exists():
            try:
                payload = json.loads(model_path.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                expected_sha256 = payload.get("report_sha256")
                if isinstance(expected_sha256, str):
                    integrity_ok = expected_sha256 == actual_sha256
        return {
            "ok": True,
            "model_version": model_version,
            "training_run_id": training_run_id,
            "report": report,
            "expected_sha256": expected_sha256,
            "actual_sha256": actual_sha256,
            "integrity_ok": integrity_ok,
        }

    def archive_models(self, *, dry_run: bool = False) -> dict[str, Any]:
        cfg = self._retention_cfg
        if not bool(cfg.get("enabled", False)):
            return {"archived": 0, "reason": "retention_disabled"}
        max_active = int(cfg.get("max_active_models", 3) or 3)
        archive_unapproved = bool(cfg.get("archive_unapproved", False))
        approvals = self._load_approvals()
        approvals.sort(key=lambda item: int(item.get("approved_ts_ms", 0) or 0), reverse=True)
        keep = approvals[:max_active] if max_active > 0 else []
        keep_set = {(item.get("model_version"), item.get("training_run_id")) for item in keep}
        to_archive = [item for item in approvals if (item.get("model_version"), item.get("training_run_id")) not in keep_set]
        archived = 0
        for item in to_archive:
            model_version = str(item.get("model_version") or "")
            training_run_id = str(item.get("training_run_id") or "")
            if not model_version or not training_run_id:
                continue
            if item.get("archived_ts_ms"):
                continue
            src = self._model_dir(model_version, training_run_id)
            if not src.exists():
                continue
            dest_root = self._archive_root()
            dest = dest_root / model_version / training_run_id
            if dest.exists():
                dest = dest_root / model_version / f"{training_run_id}-{int(time.time())}"
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
            item["archived_ts_ms"] = int(time.time() * 1000)
            item["archive_path"] = str(dest)
            archived += 1
            append_audit_event(
                action="state.training.archived",
                actor="state_jepa_training",
                outcome="ok",
                details={"model_version": model_version, "training_run_id": training_run_id, "archive_path": str(dest)},
            )

        if archive_unapproved:
            archived += self._archive_unapproved(dry_run=dry_run)

        if archived > 0 and not dry_run:
            self._approvals_path.write_text(canonical_dumps(approvals), encoding="utf-8")
        return {"archived": archived, "kept": len(keep), "total_approved": len(approvals)}

    def _archive_unapproved(self, *, dry_run: bool) -> int:
        approved = {(item.get("model_version"), item.get("training_run_id")) for item in self._load_approvals()}
        archived = 0
        for model_dir in self._root.glob("*/*"):
            model_path = model_dir / "model.json"
            if not model_path.exists():
                continue
            try:
                payload = json.loads(model_path.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
            model_version = str(payload.get("model_version") or model_dir.parent.name)
            training_run_id = str(payload.get("training_run_id") or model_dir.name)
            if (model_version, training_run_id) in approved:
                continue
            dest_root = self._archive_root()
            dest = dest_root / model_version / training_run_id
            if dest.exists():
                dest = dest_root / model_version / f"{training_run_id}-{int(time.time())}"
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(model_dir), str(dest))
            archived += 1
            append_audit_event(
                action="state.training.archived_unapproved",
                actor="state_jepa_training",
                outcome="ok",
                details={"model_version": model_version, "training_run_id": training_run_id, "archive_path": str(dest)},
            )
        return archived

    def _model_dir(self, model_version: str, training_run_id: str) -> Path:
        return self._root / model_version / training_run_id

    def _archive_root(self) -> Path:
        raw = str(self._retention_cfg.get("archive_dir") or "").strip()
        if raw:
            return Path(raw)
        return self._root.parent / "jepa_archive"

    def _resolve_archive_path(self, model_version: str, training_run_id: str) -> Path | None:
        approvals = self._load_approvals()
        for item in approvals:
            if (
                item.get("model_version") == model_version
                and item.get("training_run_id") == training_run_id
                and item.get("archive_path")
            ):
                path = Path(str(item.get("archive_path")))
                if path.exists():
                    return path
        archive_root = self._archive_root()
        candidate = archive_root / model_version / training_run_id
        return candidate if candidate.exists() else None

    def _load_approvals(self) -> list[dict[str, Any]]:
        if not self._approvals_path.exists():
            return []
        try:
            payload = json.loads(self._approvals_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def _is_approved(self, model_version: str, training_run_id: str, signature: str) -> bool:
        approvals = self._load_approvals()
        for item in approvals:
            if (
                item.get("model_version") == model_version
                and item.get("training_run_id") == training_run_id
                and item.get("signature") == signature
            ):
                return True
        return False

    def _sign_bytes(self, payload: bytes) -> str:
        key = self._load_key()
        digest = hmac.new(key, payload, "sha256").hexdigest()
        return digest

    def _verify_signature(self, payload: bytes, signature: str) -> bool:
        expected = self._sign_bytes(payload)
        return hmac.compare_digest(expected, signature.strip())

    def _load_key(self) -> bytes:
        if self._key_path.exists():
            data = self._key_path.read_text(encoding="utf-8").strip()
            try:
                return bytes.fromhex(data)
            except Exception:
                return data.encode("utf-8")
        key = os.urandom(32)
        self._key_path.write_text(key.hex(), encoding="utf-8")
        return key

    def _run_golden_eval(self) -> dict[str, Any]:
        try:
            fixture_path = resolve_repo_path("tests/fixtures/state_golden.json")
            payload = load_state_eval_cases(fixture_path)
            cases = payload.get("cases", [])
            states = payload.get("states", [])
            if not isinstance(cases, list) or not isinstance(states, list):
                raise ValueError("invalid_state_golden_fixture")
            config = self.context.config if isinstance(self.context.config, dict) else {}
            summary = run_state_eval(config, cases=cases, states=states)
            return summary if isinstance(summary, dict) else {"ok": False, "error": "eval_failed"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


def _sanitize_eval(payload: Any) -> Any:
    if isinstance(payload, bool):
        return payload
    if isinstance(payload, int):
        return payload
    if isinstance(payload, float):
        text = f"{payload:.6f}"
        return text.rstrip("0").rstrip(".") if "." in text else text
    if payload is None or isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return {str(k): _sanitize_eval(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_sanitize_eval(v) for v in payload]
    return str(payload)


def _dataset_fingerprint(
    spans: Any,
    edges: Any,
    evidence: Any,
) -> str:
    span_ids = sorted({str(span.get("state_id") or "") for span in spans if isinstance(span, dict) and span.get("state_id")})
    span_embeds = sorted(
        {
            compute_embedding_hash(_span_embedding_blob(span))
            for span in spans
            if isinstance(span, dict)
            and isinstance(span.get("z_embedding"), dict)
            and _span_embedding_blob(span)
        }
    )
    edge_ids = sorted({str(edge.get("edge_id") or "") for edge in edges if isinstance(edge, dict) and edge.get("edge_id")})
    evidence_ids = sorted(
        {
            str(ref.get("sha256") or ref.get("media_id") or "")
            for ref in evidence
            if isinstance(ref, dict) and (ref.get("sha256") or ref.get("media_id"))
        }
    )
    payload = {
        "spans": span_ids,
        "span_embeddings": span_embeds,
        "edges": edge_ids,
        "evidence": evidence_ids,
    }
    return sha256_text(canonical_dumps(payload))


def _span_embedding_blob(span: dict[str, Any]) -> bytes:
    emb = span.get("z_embedding", {}) if isinstance(span.get("z_embedding"), dict) else {}
    blob = emb.get("blob")
    if isinstance(blob, str):
        import base64

        return base64.b64decode(blob.encode("ascii"))
    if isinstance(blob, (bytes, bytearray)):
        return bytes(blob)
    return b""


def _features_from_spans(spans: Any) -> list[list[float]]:
    if not isinstance(spans, list):
        return []
    ordered = [span for span in spans if isinstance(span, dict)]
    ordered.sort(key=lambda s: (int(s.get("ts_start_ms", 0) or 0), str(s.get("state_id") or "")))
    features: list[list[float]] = []
    for span in ordered:
        emb = span.get("z_embedding", {}) if isinstance(span.get("z_embedding"), dict) else {}
        vec = _unpack_embedding(emb)
        if vec:
            features.append(vec)
    return features


def _unpack_embedding(embedding: dict[str, Any]) -> list[float]:
    if not isinstance(embedding, dict):
        return []
    blob = embedding.get("blob")
    if isinstance(blob, str):
        import base64

        blob = base64.b64decode(blob.encode("ascii"))
    if not isinstance(blob, (bytes, bytearray)):
        return []
    data = bytes(blob)
    if not data:
        return []
    vec: list[float] = []
    for idx in range(0, len(data), 2):
        vec.append(_f16_to_float(data[idx : idx + 2]))
    return vec


def _f16_to_float(blob: bytes) -> float:
    import struct

    if len(blob) != 2:
        return 0.0
    try:
        return float(struct.unpack("e", blob)[0])
    except Exception:
        return 0.0
