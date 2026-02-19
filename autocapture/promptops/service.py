"""Shared PromptOps service helpers.

This module centralizes PromptOps layer instantiation so callers do not repeatedly
reload prompt bundle/plugin state for every query in the same process.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

from autocapture.promptops.engine import PromptOpsLayer


def _config_fingerprint(config: dict[str, Any]) -> str:
    try:
        payload = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    except Exception:
        payload = repr(config)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PromptOpsService:
    """Process-local cache for PromptOps layer instances."""

    _lock = threading.RLock()
    _layers: dict[str, PromptOpsLayer] = {}
    _apis: dict[str, Any] = {}

    @classmethod
    def get_layer(cls, config: dict[str, Any]) -> PromptOpsLayer:
        cfg = config if isinstance(config, dict) else {}
        key = _config_fingerprint(cfg)
        with cls._lock:
            layer = cls._layers.get(key)
            if layer is None:
                layer = PromptOpsLayer(cfg)
                cls._layers[key] = layer
            return layer

    @classmethod
    def clear_cache(cls) -> None:
        with cls._lock:
            cls._layers.clear()
            cls._apis.clear()

    @classmethod
    def cache_size(cls) -> int:
        with cls._lock:
            return int(len(cls._layers))

    @classmethod
    def get_api(cls, config: dict[str, Any]) -> Any:
        cfg = config if isinstance(config, dict) else {}
        key = _config_fingerprint(cfg)
        with cls._lock:
            api = cls._apis.get(key)
            if api is None:
                from autocapture.promptops.api import PromptOpsAPI

                api = PromptOpsAPI(cfg)
                cls._apis[key] = api
            return api


def get_promptops_layer(config: dict[str, Any]) -> PromptOpsLayer:
    return PromptOpsService.get_layer(config)


def get_promptops_api(config: dict[str, Any]) -> Any:
    return PromptOpsService.get_api(config)
