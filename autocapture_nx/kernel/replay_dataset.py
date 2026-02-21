"""Dataset replay: re-run extraction/indexing against existing evidence.

EXEC-04: Replay must not mutate original evidence artifacts. This implementation
creates a new run_id namespace for derived artifacts while reading evidence
records/blobs from the existing store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autocapture_nx.kernel.derived_records import (
    build_derivation_edge,
    build_text_record,
    derivation_edge_id,
    derived_text_record_id,
    extract_text_payload,
)


@dataclass(frozen=True)
class ReplayReport:
    ok: bool
    source_run_id: str
    target_run_id: str
    evidence_scanned: int
    derived_written: int
    edge_written: int
    errors: list[str]


def replay_dataset(
    system: Any,
    *,
    source_run_id: str,
    target_run_id: str,
    limit: int = 200,
) -> ReplayReport:
    source_run_id = str(source_run_id or "").strip()
    target_run_id = str(target_run_id or "").strip()
    if not source_run_id or not target_run_id:
        return ReplayReport(
            ok=False,
            source_run_id=source_run_id,
            target_run_id=target_run_id,
            evidence_scanned=0,
            derived_written=0,
            edge_written=0,
            errors=["missing_run_id"],
        )

    try:
        metadata = system.get("storage.metadata")
    except Exception:
        metadata = None
    try:
        media = system.get("storage.media")
    except Exception:
        media = None
    if metadata is None or media is None:
        return ReplayReport(
            ok=False,
            source_run_id=source_run_id,
            target_run_id=target_run_id,
            evidence_scanned=0,
            derived_written=0,
            edge_written=0,
            errors=["missing_storage"],
        )

    try:
        ocr = system.get("ocr.engine")
    except Exception:
        ocr = None
    try:
        vlm = system.get("vision.extractor")
    except Exception:
        vlm = None

    config = getattr(system, "config", {}) if hasattr(system, "config") else {}

    evidence_scanned = 0
    derived_written = 0
    edge_written = 0
    errors: list[str] = []

    keys = []
    try:
        keys = list(getattr(metadata, "keys", lambda: [])())
    except Exception:
        keys = []
    for record_id in sorted(str(k) for k in keys if str(k).startswith(source_run_id + "/")):
        if evidence_scanned >= max(1, int(limit)):
            break
        try:
            record = metadata.get(record_id, {})
        except Exception:
            record = {}
        if not isinstance(record, dict):
            continue
        if str(record.get("record_type", "")).strip() != "evidence.capture.frame":
            continue
        evidence_scanned += 1

        # Read blob for the evidence id. Best-effort: use open_stream when available.
        blob = None
        stream_fn = getattr(media, "open_stream", None)
        if callable(stream_fn):
            try:
                with stream_fn(record_id) as handle:
                    blob = handle.read()
            except Exception:
                blob = None
        if blob is None:
            try:
                blob = media.get(record_id)
            except Exception:
                blob = None
        if not blob:
            continue

        extractors: list[tuple[str, str, Any]] = []
        if ocr is not None:
            try:
                for provider_id, extractor in _capability_providers(ocr, "ocr.engine"):
                    extractors.append(("ocr", provider_id, extractor))
            except Exception:
                pass
        if vlm is not None:
            try:
                for provider_id, extractor in _capability_providers(vlm, "vision.extractor"):
                    extractors.append(("vlm", provider_id, extractor))
            except Exception:
                pass
        if not extractors:
            continue

        # Emit derived artifacts under target_run_id, but point back to the source evidence id.
        for kind, provider_id, extractor in extractors:
            derived_id = derived_text_record_id(
                kind=kind,
                run_id=target_run_id,
                provider_id=str(provider_id),
                source_id=record_id,
                config=config if isinstance(config, dict) else {},
            )
            try:
                if metadata.get(derived_id) is not None:
                    continue
            except Exception:
                pass
            try:
                text = extract_text_payload(extractor.extract(blob))
            except Exception:
                continue
            # Override run_id in payload to target while preserving timestamps.
            source_record = dict(record)
            source_record["run_id"] = target_run_id
            payload = build_text_record(
                kind=kind,
                text=text,
                source_id=record_id,
                source_record=source_record,
                provider_id=str(provider_id),
                config=config if isinstance(config, dict) else {},
                ts_utc=record.get("ts_utc"),
            )
            if not payload:
                continue
            try:
                if hasattr(metadata, "put_new"):
                    metadata.put_new(derived_id, payload)
                else:
                    metadata.put(derived_id, payload)
                derived_written += 1
            except Exception as exc:
                errors.append(f"write_failed:{type(exc).__name__}")
                continue

            try:
                edge_id = derivation_edge_id(target_run_id, record_id, derived_id)
                edge_payload = build_derivation_edge(
                    run_id=target_run_id,
                    parent_id=record_id,
                    child_id=derived_id,
                    relation_type="derived_from",
                    span_ref=payload.get("span_ref", {}) if isinstance(payload, dict) else {},
                    method=kind,
                )
                if hasattr(metadata, "put_new"):
                    metadata.put_new(edge_id, edge_payload)
                else:
                    metadata.put(edge_id, edge_payload)
                edge_written += 1
            except Exception:
                pass

    return ReplayReport(
        ok=True,
        source_run_id=source_run_id,
        target_run_id=target_run_id,
        evidence_scanned=evidence_scanned,
        derived_written=derived_written,
        edge_written=edge_written,
        errors=errors,
    )


def _capability_providers(plugin: Any, cap_name: str) -> list[tuple[str, Any]]:
    # Mirrors autocapture_nx.kernel.query capability enumeration, but keeps replay lightweight.
    caps = getattr(plugin, "capabilities", None)
    if not callable(caps):
        return []
    provided = caps()
    if not isinstance(provided, dict):
        return []
    raw = provided.get(cap_name)
    if raw is None:
        return []
    if isinstance(raw, dict):
        out: list[tuple[str, Any]] = []
        for pid, extractor in raw.items():
            pid_str = str(pid).strip()
            if pid_str and extractor is not None:
                out.append((pid_str, extractor))
        return out
    # Single provider.
    return [("default", raw)]

