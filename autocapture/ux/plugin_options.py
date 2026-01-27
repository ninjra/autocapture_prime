"""Plugin option schemas for UX surfaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CAPABILITY_POLICY_FIELDS = {
    "mode",
    "preferred",
    "provider_ids",
    "fanout",
    "max_providers",
}

STAGE_POLICY_FIELDS = {
    "enabled",
    "provider_ids",
    "fanout",
    "max_providers",
}


def _label_from_path(path: str) -> str:
    return path.split(".")[-1].replace("_", " ").title()


def _capability_policy_target(path: str) -> tuple[str, str] | None:
    parts = path.split(".")
    if len(parts) < 4:
        return None
    if parts[0] != "plugins" or parts[1] != "capabilities":
        return None
    for idx in range(2, len(parts)):
        if parts[idx] in CAPABILITY_POLICY_FIELDS:
            capability = ".".join(parts[2:idx])
            field = parts[idx]
            if capability:
                return capability, field
    return None


def _stage_policy_target(path: str) -> tuple[str, str] | None:
    parts = path.split(".")
    if len(parts) < 5:
        return None
    if parts[0] != "processing" or parts[1] != "sst" or parts[2] != "stage_providers":
        return None
    for idx in range(3, len(parts)):
        if parts[idx] in STAGE_POLICY_FIELDS:
            stage = ".".join(parts[3:idx])
            field = parts[idx]
            if stage:
                return stage, field
    return None


def _get_by_path(data: dict[str, Any], path: str) -> Any:
    cap_target = _capability_policy_target(path)
    if cap_target is not None:
        capability, field = cap_target
        plugins_cfg = data.get("plugins", {}) if isinstance(data, dict) else {}
        caps_cfg = plugins_cfg.get("capabilities", {}) if isinstance(plugins_cfg, dict) else {}
        policy = caps_cfg.get(capability, {}) if isinstance(caps_cfg, dict) else {}
        if isinstance(policy, dict):
            return policy.get(field)
        return None
    stage_target = _stage_policy_target(path)
    if stage_target is not None:
        stage, field = stage_target
        processing_cfg = data.get("processing", {}) if isinstance(data, dict) else {}
        sst_cfg = processing_cfg.get("sst", {}) if isinstance(processing_cfg, dict) else {}
        stage_cfg = sst_cfg.get("stage_providers", {}) if isinstance(sst_cfg, dict) else {}
        policy = stage_cfg.get(stage, {}) if isinstance(stage_cfg, dict) else {}
        if isinstance(policy, dict):
            return policy.get(field)
        return None
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _schema_for_path(schema: dict[str, Any], path: str) -> dict[str, Any] | None:
    cap_target = _capability_policy_target(path)
    if cap_target is not None:
        _capability, field = cap_target
        plugins_schema = schema.get("properties", {}).get("plugins", {})
        caps_schema = plugins_schema.get("properties", {}).get("capabilities", {})
        policy_schema = caps_schema.get("additionalProperties", {})
        if isinstance(policy_schema, dict):
            return policy_schema.get("properties", {}).get(field)
        return None
    stage_target = _stage_policy_target(path)
    if stage_target is not None:
        _stage, field = stage_target
        processing_schema = schema.get("properties", {}).get("processing", {})
        sst_schema = processing_schema.get("properties", {}).get("sst", {})
        stage_schema = sst_schema.get("properties", {}).get("stage_providers", {})
        policy_schema = stage_schema.get("additionalProperties", {})
        if isinstance(policy_schema, dict):
            return policy_schema.get("properties", {}).get(field)
        return None
    node = schema.get("properties", {})
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
        if not isinstance(node, dict):
            return None
        node = node.get("properties", node)
    return node if isinstance(node, dict) else None


PLUGIN_OPTION_PATHS: dict[str, list[str]] = {
    "builtin.capture.windows": [
        "capture.video.backend",
        "capture.video.fps_target",
        "capture.video.segment_seconds",
        "capture.video.container",
        "capture.video.encoder",
        "capture.video.monitor_index",
        "capture.video.jpeg_quality",
        "capture.video.resolution",
        "capture.cursor.enabled",
        "capture.cursor.include_shape",
    ],
    "mx.core.capture_win": [
        "capture.video.backend",
        "capture.video.fps_target",
        "capture.video.segment_seconds",
        "capture.video.container",
        "capture.video.encoder",
        "capture.video.monitor_index",
        "capture.video.jpeg_quality",
        "capture.video.resolution",
    ],
    "builtin.capture.audio.windows": [
        "capture.audio.enabled",
        "capture.audio.mode",
        "capture.audio.microphone",
        "capture.audio.system_audio",
        "capture.audio.sample_rate",
        "capture.audio.channels",
        "capture.audio.blocksize",
        "capture.audio.queue_max",
        "capture.audio.encoding",
        "capture.audio.ffmpeg_path",
        "capture.audio.device",
    ],
    "builtin.tracking.input.windows": [
        "capture.input_tracking.mode",
        "capture.input_tracking.flush_interval_ms",
        "capture.input_tracking.store_derived",
    ],
    "builtin.window.metadata.windows": [
        "capture.window_metadata.enabled",
        "capture.window_metadata.sample_hz",
    ],
    "builtin.backpressure.basic": [
        "backpressure.max_fps",
        "backpressure.min_fps",
        "backpressure.max_bitrate_kbps",
        "backpressure.min_bitrate_kbps",
        "backpressure.max_queue_depth",
        "backpressure.max_segment_seconds",
        "backpressure.min_segment_seconds",
    ],
    "builtin.runtime.governor": [
        "runtime.active_window_s",
        "runtime.idle_window_s",
        "runtime.mode_enforcement.suspend_workers",
        "runtime.mode_enforcement.suspend_deadline_ms",
        "runtime.budgets.window_s",
        "runtime.budgets.window_budget_ms",
        "runtime.budgets.per_job_max_ms",
        "runtime.budgets.max_jobs_per_window",
        "runtime.budgets.max_heavy_concurrency",
        "runtime.budgets.preempt_grace_ms",
        "runtime.budgets.min_idle_seconds",
        "runtime.budgets.allow_heavy_during_active",
        "runtime.telemetry.enabled",
        "runtime.telemetry.emit_interval_s",
    ],
    "builtin.processing.sst.pipeline": [
        "processing.sst.enabled",
        "processing.sst.heavy_on_boundary",
        "processing.sst.heavy_always",
        "processing.sst.d_stable",
        "processing.sst.d_boundary",
        "processing.sst.diff_threshold_bp",
        "processing.sst.tile_max_px",
        "processing.sst.tile_overlap_px",
        "processing.sst.tile_add_full_frame",
        "processing.sst.tile_refine_enabled",
        "processing.sst.tile_refine_low_conf_bp",
        "processing.sst.tile_refine_padding_px",
        "processing.sst.tile_refine_max_patches",
        "processing.sst.tile_refine_cluster_gap_px",
        "processing.sst.ocr_min_conf_bp",
        "processing.sst.ocr_nms_iou_bp",
        "processing.sst.ocr_max_tokens",
        "processing.sst.table_min_rows",
        "processing.sst.table_min_cols",
        "processing.sst.code_min_keywords",
        "processing.sst.code_detect_caret",
        "processing.sst.code_detect_selection",
        "processing.sst.redact_enabled",
        "plugins.conflicts.enforce",
        "plugins.conflicts.allow_pairs",
        "plugins.capabilities.processing.pipeline.mode",
        "plugins.capabilities.processing.pipeline.preferred",
        "plugins.capabilities.processing.pipeline.provider_ids",
        "plugins.capabilities.processing.pipeline.fanout",
        "plugins.capabilities.processing.pipeline.max_providers",
        "plugins.capabilities.processing.stage.hooks.mode",
        "plugins.capabilities.processing.stage.hooks.preferred",
        "plugins.capabilities.processing.stage.hooks.provider_ids",
        "plugins.capabilities.processing.stage.hooks.fanout",
        "plugins.capabilities.processing.stage.hooks.max_providers",
        "processing.sst.stage_providers.ingest.frame.enabled",
        "processing.sst.stage_providers.ingest.frame.provider_ids",
        "processing.sst.stage_providers.ingest.frame.fanout",
        "processing.sst.stage_providers.ingest.frame.max_providers",
        "processing.sst.stage_providers.preprocess.normalize.enabled",
        "processing.sst.stage_providers.preprocess.normalize.provider_ids",
        "processing.sst.stage_providers.preprocess.normalize.fanout",
        "processing.sst.stage_providers.preprocess.normalize.max_providers",
        "processing.sst.stage_providers.preprocess.tile.enabled",
        "processing.sst.stage_providers.preprocess.tile.provider_ids",
        "processing.sst.stage_providers.preprocess.tile.fanout",
        "processing.sst.stage_providers.preprocess.tile.max_providers",
        "processing.sst.stage_providers.ocr.onnx.enabled",
        "processing.sst.stage_providers.ocr.onnx.provider_ids",
        "processing.sst.stage_providers.ocr.onnx.fanout",
        "processing.sst.stage_providers.ocr.onnx.max_providers",
        "processing.sst.stage_providers.vision.vlm.enabled",
        "processing.sst.stage_providers.vision.vlm.provider_ids",
        "processing.sst.stage_providers.vision.vlm.fanout",
        "processing.sst.stage_providers.vision.vlm.max_providers",
        "processing.sst.stage_providers.layout.assemble.enabled",
        "processing.sst.stage_providers.layout.assemble.provider_ids",
        "processing.sst.stage_providers.layout.assemble.fanout",
        "processing.sst.stage_providers.layout.assemble.max_providers",
        "processing.sst.stage_providers.extract.table.enabled",
        "processing.sst.stage_providers.extract.table.provider_ids",
        "processing.sst.stage_providers.extract.table.fanout",
        "processing.sst.stage_providers.extract.table.max_providers",
        "processing.sst.stage_providers.extract.spreadsheet.enabled",
        "processing.sst.stage_providers.extract.spreadsheet.provider_ids",
        "processing.sst.stage_providers.extract.spreadsheet.fanout",
        "processing.sst.stage_providers.extract.spreadsheet.max_providers",
        "processing.sst.stage_providers.extract.code.enabled",
        "processing.sst.stage_providers.extract.code.provider_ids",
        "processing.sst.stage_providers.extract.code.fanout",
        "processing.sst.stage_providers.extract.code.max_providers",
        "processing.sst.stage_providers.extract.chart.enabled",
        "processing.sst.stage_providers.extract.chart.provider_ids",
        "processing.sst.stage_providers.extract.chart.fanout",
        "processing.sst.stage_providers.extract.chart.max_providers",
        "processing.sst.stage_providers.ui.parse.enabled",
        "processing.sst.stage_providers.ui.parse.provider_ids",
        "processing.sst.stage_providers.ui.parse.fanout",
        "processing.sst.stage_providers.ui.parse.max_providers",
        "processing.sst.stage_providers.track.cursor.enabled",
        "processing.sst.stage_providers.track.cursor.provider_ids",
        "processing.sst.stage_providers.track.cursor.fanout",
        "processing.sst.stage_providers.track.cursor.max_providers",
        "processing.sst.stage_providers.build.state.enabled",
        "processing.sst.stage_providers.build.state.provider_ids",
        "processing.sst.stage_providers.build.state.fanout",
        "processing.sst.stage_providers.build.state.max_providers",
        "processing.sst.stage_providers.match.ids.enabled",
        "processing.sst.stage_providers.match.ids.provider_ids",
        "processing.sst.stage_providers.match.ids.fanout",
        "processing.sst.stage_providers.match.ids.max_providers",
        "processing.sst.stage_providers.build.delta.enabled",
        "processing.sst.stage_providers.build.delta.provider_ids",
        "processing.sst.stage_providers.build.delta.fanout",
        "processing.sst.stage_providers.build.delta.max_providers",
        "processing.sst.stage_providers.infer.action.enabled",
        "processing.sst.stage_providers.infer.action.provider_ids",
        "processing.sst.stage_providers.infer.action.fanout",
        "processing.sst.stage_providers.infer.action.max_providers",
        "processing.sst.stage_providers.compliance.redact.enabled",
        "processing.sst.stage_providers.compliance.redact.provider_ids",
        "processing.sst.stage_providers.compliance.redact.fanout",
        "processing.sst.stage_providers.compliance.redact.max_providers",
        "processing.sst.stage_providers.persist.bundle.enabled",
        "processing.sst.stage_providers.persist.bundle.provider_ids",
        "processing.sst.stage_providers.persist.bundle.fanout",
        "processing.sst.stage_providers.persist.bundle.max_providers",
        "processing.sst.stage_providers.index.text.enabled",
        "processing.sst.stage_providers.index.text.provider_ids",
        "processing.sst.stage_providers.index.text.fanout",
        "processing.sst.stage_providers.index.text.max_providers",
    ],
    "builtin.processing.sst.ui_vlm": [
        "processing.sst.ui_vlm.enabled",
        "processing.sst.ui_vlm.max_providers",
        "processing.sst.stage_providers.ui.parse.enabled",
        "processing.sst.stage_providers.ui.parse.provider_ids",
        "processing.sst.stage_providers.ui.parse.fanout",
        "processing.sst.stage_providers.ui.parse.max_providers",
    ],
    "builtin.time.advanced": [
        "time.timezone",
        "runtime.timezone",
        "plugins.capabilities.time.intent_parser.preferred",
    ],
    "builtin.vlm.stub": [
        "models.vlm_path",
        "processing.idle.extractors.vlm",
        "processing.on_query.extractors.vlm",
        "plugins.capabilities.vision.extractor.mode",
        "plugins.capabilities.vision.extractor.provider_ids",
        "plugins.capabilities.vision.extractor.max_providers",
    ],
    "builtin.reranker.stub": [
        "models.reranker_path",
    ],
    "builtin.embedder.stub": [
        "indexing.embedder_model",
    ],
    "mx.core.embed_local": [
        "indexing.embedder_model",
        "plugins.capabilities.embedder.text.mode",
        "plugins.capabilities.embedder.text.preferred",
    ],
    "builtin.storage.sqlcipher": [
        "storage.metadata_path",
        "storage.data_dir",
        "storage.crypto.keyring_path",
        "storage.crypto.root_key_path",
        "storage.fsync_policy",
        "storage.encryption_required",
        "storage.disk_pressure.warn_free_gb",
        "storage.disk_pressure.soft_free_gb",
        "storage.disk_pressure.critical_free_gb",
        "storage.disk_pressure.interval_s",
        "storage.forecast.enabled",
        "storage.forecast.warn_days",
        "plugins.capabilities.storage.metadata.preferred",
        "plugins.capabilities.storage.media.preferred",
        "plugins.capabilities.storage.entity_map.preferred",
    ],
    "builtin.storage.encrypted": [
        "storage.media_dir",
        "storage.blob_dir",
        "storage.crypto.keyring_path",
        "storage.crypto.root_key_path",
        "storage.fsync_policy",
        "storage.encryption_required",
        "storage.disk_pressure.warn_free_gb",
        "storage.disk_pressure.soft_free_gb",
        "storage.disk_pressure.critical_free_gb",
        "storage.disk_pressure.interval_s",
        "storage.forecast.enabled",
        "storage.forecast.warn_days",
    ],
    "mx.core.storage_sqlite": [
        "storage.metadata_path",
        "storage.vector_path",
        "storage.lexical_path",
        "storage.data_dir",
        "plugins.capabilities.storage.metadata.preferred",
        "plugins.capabilities.storage.media.preferred",
        "plugins.capabilities.storage.entity_map.preferred",
    ],
    "builtin.ocr.stub": [
        "processing.idle.extractors.ocr",
        "processing.on_query.extractors.ocr",
        "plugins.capabilities.ocr.engine.mode",
        "plugins.capabilities.ocr.engine.provider_ids",
        "plugins.capabilities.ocr.engine.max_providers",
    ],
    "mx.prompts.default": [
        "promptops.enabled",
        "promptops.mode",
        "promptops.strategy",
        "promptops.max_chars",
        "promptops.max_tokens",
        "promptops.min_pass_rate_pct",
        "promptops.require_citations",
    ],
    "mx.core.llm_local": [
        "llm.model",
    ],
    "mx.core.ocr_local": [
        "processing.idle.extractors.ocr",
        "processing.on_query.extractors.ocr",
        "plugins.capabilities.ocr.engine.mode",
        "plugins.capabilities.ocr.engine.provider_ids",
        "plugins.capabilities.ocr.engine.max_providers",
    ],
    "mx.core.llm_openai_compat": [
        "gateway.openai_base_url",
        "privacy.cloud.enabled",
        "privacy.cloud.allow_images",
    ],
    "mx.core.vector_local": [
        "indexing.vector_backend",
        "indexing.qdrant.url",
        "indexing.qdrant.collection",
        "plugins.capabilities.retrieval.strategy.mode",
        "plugins.capabilities.retrieval.strategy.preferred",
    ],
    "builtin.retrieval.basic": [
        "retrieval.limit",
        "retrieval.vector_limit",
        "retrieval.fast_threshold",
        "retrieval.fusion_threshold",
        "plugins.capabilities.retrieval.strategy.mode",
        "plugins.capabilities.retrieval.strategy.preferred",
    ],
    "mx.research.default": [
        "research.enabled",
        "research.interval_s",
        "research.threshold_pct",
        "research.watchlist.tags",
    ],
}


def build_plugin_options(config: dict[str, Any]) -> dict[str, Any]:
    schema_path = Path("contracts/config_schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    options: dict[str, Any] = {}
    for plugin_id, paths in PLUGIN_OPTION_PATHS.items():
        items = []
        for path in paths:
            value = _get_by_path(config, path)
            schema_node = _schema_for_path(schema, path)
            field_type = None
            if isinstance(schema_node, dict):
                field_type = schema_node.get("type")
            items.append(
                {
                    "id": path,
                    "label": _label_from_path(path),
                    "path": path,
                    "type": field_type,
                    "value": value,
                }
            )
        options[plugin_id] = items
    return options
