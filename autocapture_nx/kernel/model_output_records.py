"""Canonical model-output record helpers.

These records are designed for:
- performance: keep the structured record small; store heavy artifacts elsewhere
- accuracy: preserve raw model output (stringified JSON) + normalized text
- security: raw-first local persistence (no masking locally)
- citeability: stable hashes + stable record ids
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from autocapture_nx.kernel.hashing import sha256_canonical, sha256_text
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.kernel.loader import _canonicalize_config_for_hash

from .derived_records import build_span_ref, model_identity


def model_output_record_id(
    *,
    modality: str,
    run_id: str,
    provider_id: str,
    source_id: str,
    model_digest: str,
) -> str:
    provider_component = encode_record_id_component(provider_id)
    digest_component = encode_record_id_component((model_digest or "model")[:16])
    encoded_source = encode_record_id_component(source_id)
    mod_component = encode_record_id_component(modality)
    return f"{run_id}/derived.model.output/{mod_component}/{provider_component}/{digest_component}/{encoded_source}"


def _json_stringify(obj: Any) -> str:
    if obj is None:
        return "null"
    if isinstance(obj, str):
        return obj

    def _default(v: Any) -> Any:
        # Avoid non-serializable objects exploding persistence; keep raw-first by
        # preserving a lossless-ish string representation.
        try:
            return v.__dict__
        except Exception:
            return repr(v)

    try:
        return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=_default, separators=(",", ":"))
    except Exception:
        return repr(obj)


def _prompt_hash(modality: str, provider_id: str, config: dict[str, Any]) -> str:
    models_cfg = config.get("models", {}) if isinstance(config, dict) else {}
    prompt = ""
    if modality == "vlm" and isinstance(models_cfg, dict):
        prompt = str(models_cfg.get("vlm_prompt") or "")
    payload = {
        "schema_version": 1,
        "modality": modality,
        "provider_id": str(provider_id),
        "prompt": prompt,
        "models": models_cfg if isinstance(models_cfg, dict) else {},
    }
    # Use config float canonicalization to avoid canonical JSON float bans.
    return sha256_canonical(_canonicalize_config_for_hash(payload))


def build_model_output_record(
    *,
    modality: str,
    provider_id: str,
    response: Any,
    extracted_text: str,
    source_id: str,
    source_record: dict[str, Any],
    config: dict[str, Any],
    ts_utc: str | None,
) -> dict[str, Any]:
    run_id = str(source_record.get("run_id") or (source_id.split("/", 1)[0] if "/" in source_id else "run"))
    ts = str(ts_utc or source_record.get("ts_utc") or source_record.get("ts_start_utc") or datetime.now(timezone.utc).isoformat())
    identity = model_identity(modality, provider_id, config)
    output_json = _json_stringify(response)
    output_sha = sha256_text(output_json)
    prompt_hash = _prompt_hash(modality, provider_id, config)
    span_ref = build_span_ref(source_record, source_id)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "derived.model.output",
        "run_id": run_id,
        "ts_utc": ts,
        "modality": str(modality),
        "source_id": str(source_id),
        "parent_evidence_id": str(source_id),
        "span_ref": span_ref,
        "provider_id": str(provider_id),
        "model_id": str(identity.get("model_id") or ""),
        "model_digest": str(identity.get("model_digest") or ""),
        "model_provider": str(identity.get("model_provider") or provider_id),
        "prompt_hash": str(prompt_hash),
        "output_text": str(extracted_text or ""),
        # Store full raw output as a string to keep canonical hashing stable even
        # when the model emits floats / non-JSON payloads.
        "output_json": str(output_json),
        "output_sha256": str(output_sha),
        "embeddings": [],
        "metrics": {
            "output_chars": int(len(output_json)),
            "text_chars": int(len(extracted_text or "")),
        },
        "provenance": {},
    }
    payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
    return payload

