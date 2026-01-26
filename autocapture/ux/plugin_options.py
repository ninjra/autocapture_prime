"""Plugin option schemas for UX surfaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _label_from_path(path: str) -> str:
    return path.split(".")[-1].replace("_", " ").title()


def _get_by_path(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _schema_for_path(schema: dict[str, Any], path: str) -> dict[str, Any] | None:
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
    ],
    "builtin.vlm.stub": [
        "models.vlm_path",
        "processing.idle.extractors.vlm",
        "processing.on_query.extractors.vlm",
    ],
    "builtin.reranker.stub": [
        "models.reranker_path",
    ],
    "builtin.embedder.stub": [
        "indexing.embedder_model",
    ],
    "mx.core.embed_local": [
        "indexing.embedder_model",
    ],
    "builtin.storage.sqlcipher": [
        "storage.metadata_path",
        "storage.data_dir",
        "storage.crypto.keyring_path",
        "storage.crypto.root_key_path",
        "storage.fsync_policy",
        "storage.encryption_required",
    ],
    "builtin.storage.encrypted": [
        "storage.media_dir",
        "storage.blob_dir",
        "storage.crypto.keyring_path",
        "storage.crypto.root_key_path",
        "storage.fsync_policy",
        "storage.encryption_required",
    ],
    "mx.core.storage_sqlite": [
        "storage.metadata_path",
        "storage.vector_path",
        "storage.lexical_path",
        "storage.data_dir",
    ],
    "builtin.ocr.stub": [
        "processing.idle.extractors.ocr",
        "processing.on_query.extractors.ocr",
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
