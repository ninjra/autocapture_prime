"""Workflow miner for state tape analysis (deterministic sequences)."""

from __future__ import annotations

from typing import Any

from autocapture_nx.kernel.hashing import sha256_text

from .ids import compute_config_hash, deterministic_id_from_parts

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


class WorkflowMiner(PluginBase):
    VERSION = "0.1.0"

    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        state_cfg = cfg.get("processing", {}).get("state_layer", {}) if isinstance(cfg.get("processing", {}), dict) else {}
        builder_cfg = state_cfg.get("builder", {}) if isinstance(state_cfg.get("builder", {}), dict) else {}
        workflow_cfg = state_cfg.get("workflow", {}) if isinstance(state_cfg.get("workflow", {}), dict) else {}
        self._seed = str(workflow_cfg.get("seed") or compute_config_hash(builder_cfg))
        self._min_support = int(workflow_cfg.get("min_support", 2) or 2)
        self._max_workflows = int(workflow_cfg.get("max_workflows", 5) or 5)
        self._min_seq_len = int(workflow_cfg.get("min_len", 2) or 2)
        self._max_seq_len = int(workflow_cfg.get("max_len", 4) or 4)
        self._max_gap_ms = int(workflow_cfg.get("max_gap_ms", 300000) or 300000)

    def capabilities(self) -> dict[str, Any]:
        return {"state.workflow_miner": self}

    def mine(self, state_tape: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
        if isinstance(state_tape, list):
            spans = [s for s in state_tape if isinstance(s, dict)]
            seed = self._seed
            model_version = _model_version_from_spans(spans)
        elif isinstance(state_tape, dict):
            spans = state_tape.get("spans", [])
            spans = [s for s in spans if isinstance(s, dict)] if isinstance(spans, list) else []
            seed = str(state_tape.get("seed") or self._seed)
            model_version = str(state_tape.get("model_version") or _model_version_from_spans(spans))
        else:
            return []

        if not spans:
            return []

        ordered = sorted(spans, key=lambda s: (int(s.get("ts_start_ms", 0) or 0), str(s.get("state_id") or "")))
        segments: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        last_ts = None
        for span in ordered:
            ts = int(span.get("ts_start_ms", 0) or 0)
            if last_ts is not None and self._max_gap_ms > 0 and ts - last_ts > self._max_gap_ms:
                if current:
                    segments.append(current)
                current = [span]
            else:
                current.append(span)
            last_ts = ts
        if current:
            segments.append(current)

        total_windows: dict[int, int] = {}
        pattern_counts: dict[tuple[str, ...], int] = {}
        representative_spans: dict[tuple[str, ...], list[str]] = {}

        for segment in segments:
            signature_seq = [_span_signature(span) for span in segment]
            span_id_seq = [str(span.get("state_id") or "") for span in segment]
            if len(signature_seq) < self._min_seq_len:
                continue
            max_len = min(self._max_seq_len, len(signature_seq))
            for length in range(self._min_seq_len, max_len + 1):
                windows = max(0, len(signature_seq) - length + 1)
                total_windows[length] = total_windows.get(length, 0) + windows
                if windows <= 0:
                    continue
                for idx in range(windows):
                    key = tuple(signature_seq[idx : idx + length])
                    pattern_counts[key] = pattern_counts.get(key, 0) + 1
                    if key not in representative_spans:
                        representative_spans[key] = list(span_id_seq[idx : idx + length])

        if not pattern_counts:
            return []
        workflows: list[dict[str, Any]] = []
        for key, count in pattern_counts.items():
            if count < self._min_support:
                continue
            length = len(key)
            denom = float(total_windows.get(length, 1) or 1.0)
            confidence = float(count) / denom
            workflow_id = deterministic_id_from_parts(
                {
                    "kind": "workflow",
                    "model_version": model_version,
                    "seed": seed,
                    "signatures": list(key),
                }
            )
            span_ids = representative_spans.get(key, list(key))
            workflows.append(
                {
                    "workflow_id": workflow_id,
                    "span_ids": span_ids,
                    "support_count": int(count),
                    "confidence": float(confidence),
                }
            )

        workflows.sort(
            key=lambda wf: (
                -int(wf.get("support_count", 0) or 0),
                -float(wf.get("confidence", 0.0) or 0.0),
                str(wf.get("workflow_id") or ""),
            )
        )
        return workflows[: self._max_workflows]


def _model_version_from_spans(spans: list[dict[str, Any]]) -> str:
    versions = set()
    for span in spans:
        prov = span.get("provenance", {}) if isinstance(span.get("provenance"), dict) else {}
        if "model_version" in prov:
            versions.add(str(prov.get("model_version") or ""))
    if not versions:
        return "unknown"
    return sorted(versions)[0]


def _span_signature(span: dict[str, Any]) -> str:
    summary = span.get("summary_features", {}) if isinstance(span.get("summary_features"), dict) else {}
    app = str(summary.get("app") or "")
    title_hash = str(summary.get("window_title_hash") or "")
    entities = summary.get("top_entities", []) if isinstance(summary.get("top_entities"), list) else []
    ent_key = "|".join(sorted(str(e) for e in entities if str(e)))
    ent_hash = sha256_text(ent_key)[:12] if ent_key else ""
    signature = "|".join([app, title_hash, ent_hash]).strip("|")
    if not signature:
        signature = str(span.get("state_id") or "")
    return signature
