"""Derived record helpers for OCR/VLM outputs and derivation edges."""

from __future__ import annotations

import json
from typing import Any

from autocapture.core.hashing import hash_text, normalize_text, TEXT_NORM_VERSION
from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.kernel.hashing import sha256_canonical, sha256_text
from autocapture_nx.kernel.ids import encode_record_id_component


def apply_producer_metadata(
    payload: dict[str, Any],
    *,
    producer_plugin_id: str,
    stage_id: str,
    input_artifact_ids: list[str] | None = None,
    input_hashes: list[str] | None = None,
    plugin_chain: list[str] | None = None,
) -> dict[str, Any]:
    out = dict(payload)
    producer = str(producer_plugin_id or "").strip()
    stage = str(stage_id or "").strip()
    if producer and not str(out.get("producer_plugin_id") or "").strip():
        out["producer_plugin_id"] = producer
    if producer and not str(out.get("source_provider_id") or "").strip():
        out["source_provider_id"] = producer
    provenance = out.get("provenance", {}) if isinstance(out.get("provenance", {}), dict) else {}
    provenance = dict(provenance)
    if producer and not str(provenance.get("plugin_id") or "").strip():
        provenance["plugin_id"] = producer
    if producer and not str(provenance.get("producer_plugin_id") or "").strip():
        provenance["producer_plugin_id"] = producer
    if stage and not str(provenance.get("stage_id") or "").strip():
        provenance["stage_id"] = stage
    if input_artifact_ids:
        ids = [str(x) for x in input_artifact_ids if str(x)]
        if ids:
            provenance["input_artifact_ids"] = ids
    if input_hashes:
        hashes = [str(x) for x in input_hashes if str(x)]
        if hashes:
            provenance["input_hashes"] = hashes
    chain = [str(x) for x in (plugin_chain or []) if str(x)]
    if producer and producer not in chain:
        chain.append(producer)
    if chain:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in chain:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        provenance["plugin_chain"] = deduped
    if provenance:
        out["provenance"] = provenance
    return out


def build_span_ref(source_record: dict[str, Any], source_id: str) -> dict[str, Any]:
    ts_start = source_record.get("ts_start_utc") or source_record.get("ts_utc")
    ts_end = source_record.get("ts_end_utc") or source_record.get("ts_utc")
    span_ref = {"kind": "time", "source_id": source_id}
    if ts_start:
        span_ref["start_ts_utc"] = ts_start
    if ts_end:
        span_ref["end_ts_utc"] = ts_end
    return span_ref


def _provider_model_override(models_cfg: dict[str, Any], provider_id: str) -> dict[str, Any] | None:
    providers = models_cfg.get("providers")
    if not isinstance(providers, dict):
        return None
    raw = providers.get(provider_id)
    if not isinstance(raw, dict):
        return None
    return raw


def model_identity(kind: str, provider_id: str, config: dict[str, Any]) -> dict[str, Any]:
    model_id = provider_id
    models_cfg = config.get("models", {}) if isinstance(config, dict) else {}
    override = _provider_model_override(models_cfg, provider_id)
    if override:
        override_id = override.get("model_id") or override.get("model_path")
        if override_id:
            model_id = str(override_id)
    else:
        if kind == "vlm" and models_cfg.get("vlm_path"):
            model_id = str(models_cfg.get("vlm_path"))
        if kind == "ocr" and models_cfg.get("ocr_path"):
            model_id = str(models_cfg.get("ocr_path"))
    params: dict[str, Any] = {"provider_id": provider_id}
    if override:
        if override.get("revision"):
            params["revision"] = override.get("revision")
        if override.get("model_path"):
            params["path"] = override.get("model_path")
        if override.get("files"):
            params["files"] = override.get("files")
    digest_seed = json.dumps({"model_id": model_id, "provider_id": provider_id, "params": params}, sort_keys=True)
    return {
        "model_id": model_id,
        "model_digest": sha256_text(digest_seed),
        "model_provider": provider_id,
        "parameters": params,
    }


def derived_text_record_id(
    *,
    kind: str,
    run_id: str,
    provider_id: str,
    source_id: str,
    config: dict[str, Any],
) -> str:
    """Compute a stable derived-text record id keyed by model identity.

    PERF-03: include extractor/model identity in the derived id so config/model
    changes do not incorrectly "hit cache" on an old derived record.
    """

    identity = model_identity(kind, provider_id, config)
    digest = str(identity.get("model_digest") or "")
    digest_component = encode_record_id_component(digest[:16] if digest else "model")
    provider_component = encode_record_id_component(provider_id)
    encoded_source = encode_record_id_component(source_id)
    return f"{run_id}/derived.text.{kind}/{provider_component}/{digest_component}/{encoded_source}"


def extract_text_payload(response: Any) -> str:
    if isinstance(response, dict):
        for key in ("text_plain", "caption", "text"):
            value = response.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                text = value.strip()
                if text:
                    return text
            else:
                return str(value)
    return ""


def build_text_record(
    *,
    kind: str,
    text: str,
    source_id: str,
    source_record: dict[str, Any],
    provider_id: str,
    config: dict[str, Any],
    ts_utc: str | None,
) -> dict[str, Any] | None:
    normalized_text = normalize_text(text)
    if not normalized_text:
        return None
    span_ref = build_span_ref(source_record, source_id)
    identity = model_identity(kind, provider_id, config)
    models_cfg = config.get("models", {}) if isinstance(config, dict) else {}
    override = _provider_model_override(models_cfg, provider_id)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "record_type": f"derived.text.{kind}",
        "run_id": (source_record.get("run_id") or source_id.split("/", 1)[0]),
        "ts_utc": ts_utc,
        "text": normalized_text,
        "text_normalized": normalized_text,
        "text_norm_version": TEXT_NORM_VERSION,
        "source_id": source_id,
        "parent_evidence_id": source_id,
        "span_ref": span_ref,
        "method": kind,
        "provider_id": provider_id,
        "model_id": identity["model_id"],
        "model_digest": identity["model_digest"],
        "model_provider": identity["model_provider"],
        "parameters": identity["parameters"],
        "content_hash": hash_text(normalized_text),
    }
    if override:
        if override.get("revision"):
            payload["model_revision"] = override.get("revision")
        if override.get("model_path"):
            payload["model_path"] = override.get("model_path")
        if override.get("files"):
            payload["model_files"] = override.get("files")
    if normalized_text != text:
        payload["text_raw"] = text
    payload = apply_producer_metadata(
        payload,
        producer_plugin_id=str(provider_id),
        stage_id=f"derived.text.{kind}",
        input_artifact_ids=[str(source_id)],
        input_hashes=[str(source_record.get("content_hash") or source_record.get("payload_hash") or "")],
        plugin_chain=[str(provider_id)],
    )
    payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
    return payload


def derivation_edge_id(run_id: str, parent_id: str, child_id: str) -> str:
    parent_token = encode_record_id_component(parent_id)
    child_token = encode_record_id_component(child_id)
    return f"{run_id}/derived.edge/{parent_token}/{child_token}"


def build_derivation_edge(
    *,
    run_id: str,
    parent_id: str,
    child_id: str,
    relation_type: str,
    span_ref: dict[str, Any],
    method: str,
) -> dict[str, Any]:
    edge = {
        "schema_version": 1,
        "record_type": "derived.graph.edge",
        "run_id": run_id,
        "ts_utc": span_ref.get("end_ts_utc") or span_ref.get("start_ts_utc"),
        "parent_id": parent_id,
        "child_id": child_id,
        "relation_type": relation_type,
        "span_ref": span_ref,
        "method": method,
    }
    edge = apply_producer_metadata(
        edge,
        producer_plugin_id=f"builtin.processing.{str(method)}",
        stage_id="derived.graph.edge",
        input_artifact_ids=[str(parent_id), str(child_id)],
        input_hashes=[],
        plugin_chain=[f"builtin.processing.{str(method)}"],
    )
    edge["content_hash"] = sha256_text(dumps(edge))
    return edge


def artifact_manifest_id(run_id: str, artifact_id: str) -> str:
    token = encode_record_id_component(str(artifact_id))
    return f"{run_id}/derived.artifact.manifest/{token}"


def build_artifact_manifest(
    *,
    run_id: str,
    artifact_id: str,
    artifact_sha256: str,
    derived_from: dict[str, Any],
    ts_utc: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "derived.artifact.manifest",
        "run_id": str(run_id),
        "ts_utc": ts_utc,
        "artifact_id": str(artifact_id),
        "artifact_sha256": str(artifact_sha256 or ""),
        "derived_from": dict(derived_from) if isinstance(derived_from, dict) else {},
    }
    model_provider = str((payload.get("derived_from") or {}).get("model_provider") or "").strip()
    producer = model_provider or "builtin.processing.pipeline"
    payload = apply_producer_metadata(
        payload,
        producer_plugin_id=producer,
        stage_id="derived.artifact.manifest",
        input_artifact_ids=[str(artifact_id)],
        input_hashes=[str(artifact_sha256 or "")],
        plugin_chain=[producer],
    )
    payload["content_hash"] = sha256_text(dumps(payload))
    return payload
