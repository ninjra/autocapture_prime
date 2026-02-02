"""Derived record helpers for OCR/VLM outputs and derivation edges."""

from __future__ import annotations

import json
from typing import Any

from autocapture.core.hashing import hash_text, normalize_text, TEXT_NORM_VERSION
from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.kernel.hashing import sha256_canonical, sha256_text
from autocapture_nx.kernel.ids import encode_record_id_component


def build_span_ref(source_record: dict[str, Any], source_id: str) -> dict[str, Any]:
    ts_start = source_record.get("ts_start_utc") or source_record.get("ts_utc")
    ts_end = source_record.get("ts_end_utc") or source_record.get("ts_utc")
    span_ref = {"kind": "time", "source_id": source_id}
    if ts_start:
        span_ref["start_ts_utc"] = ts_start
    if ts_end:
        span_ref["end_ts_utc"] = ts_end
    return span_ref


def model_identity(kind: str, provider_id: str, config: dict[str, Any]) -> dict[str, Any]:
    model_id = provider_id
    models_cfg = config.get("models", {}) if isinstance(config, dict) else {}
    if kind == "vlm" and models_cfg.get("vlm_path"):
        model_id = str(models_cfg.get("vlm_path"))
    if kind == "ocr" and models_cfg.get("ocr_path"):
        model_id = str(models_cfg.get("ocr_path"))
    params = {"provider_id": provider_id}
    digest_seed = json.dumps({"model_id": model_id, "provider_id": provider_id, "params": params}, sort_keys=True)
    return {
        "model_id": model_id,
        "model_digest": sha256_text(digest_seed),
        "model_provider": provider_id,
        "parameters": params,
    }


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
    payload: dict[str, Any] = {
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
    if normalized_text != text:
        payload["text_raw"] = text
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
        "record_type": "derived.graph.edge",
        "run_id": run_id,
        "ts_utc": span_ref.get("end_ts_utc") or span_ref.get("start_ts_utc"),
        "parent_id": parent_id,
        "child_id": child_id,
        "relation_type": relation_type,
        "span_ref": span_ref,
        "method": method,
    }
    edge["content_hash"] = sha256_text(dumps(edge))
    return edge
