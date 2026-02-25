"""Shared PromptOps service helpers.

This module centralizes PromptOps layer instantiation so callers do not repeatedly
reload prompt bundle/plugin state for every query in the same process.
"""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import os
import threading
from typing import Any

from autocapture.promptops.engine import PromptOpsLayer


def _cache_fingerprint_payload(config: dict[str, Any]) -> dict[str, Any]:
    cfg = config if isinstance(config, dict) else {}
    paths = cfg.get("paths", {}) if isinstance(cfg.get("paths", {}), dict) else {}
    storage = cfg.get("storage", {}) if isinstance(cfg.get("storage", {}), dict) else {}
    plugins = cfg.get("plugins", {}) if isinstance(cfg.get("plugins", {}), dict) else {}
    promptops = cfg.get("promptops", {}) if isinstance(cfg.get("promptops", {}), dict) else {}
    # Important: use only PromptOps-relevant config so mutable runtime fields
    # do not create unbounded cache-key churn per query.
    return {
        "paths": {"data_dir": paths.get("data_dir")},
        "storage": {"data_dir": storage.get("data_dir")},
        "plugins": plugins,
        "promptops": promptops,
    }


def _config_fingerprint(config: dict[str, Any]) -> str:
    try:
        payload = json.dumps(
            _cache_fingerprint_payload(config),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        )
    except Exception:
        payload = repr(config)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _service_cache_max_entries(config: dict[str, Any] | None = None) -> int:
    default_cap = 16
    env_raw = str(os.environ.get("AUTOCAPTURE_PROMPTOPS_SERVICE_CACHE_MAX_ENTRIES") or "").strip()
    cfg_raw: Any = None
    if isinstance(config, dict):
        promptops_cfg = config.get("promptops", {})
        if isinstance(promptops_cfg, dict):
            service_cache_cfg = promptops_cfg.get("service_cache", {})
            if isinstance(service_cache_cfg, dict) and "max_entries" in service_cache_cfg:
                cfg_raw = service_cache_cfg.get("max_entries")
            elif "service_cache_max_entries" in promptops_cfg:
                cfg_raw = promptops_cfg.get("service_cache_max_entries")
    raw = env_raw if env_raw else cfg_raw
    try:
        cap = int(raw) if raw is not None and str(raw).strip() else default_cap
    except Exception:
        cap = default_cap
    return max(1, min(256, cap))


class PromptOpsService:
    """Process-local cache for PromptOps layer instances."""

    _lock = threading.RLock()
    _layers: "OrderedDict[str, PromptOpsLayer]" = OrderedDict()
    _apis: "OrderedDict[str, Any]" = OrderedDict()

    @classmethod
    def _evict_overflow_locked(cls, *, cap: int) -> None:
        limit = max(1, int(cap))
        while len(cls._layers) > limit:
            key, _value = cls._layers.popitem(last=False)
            cls._apis.pop(key, None)
        while len(cls._apis) > limit:
            key, _value = cls._apis.popitem(last=False)
            cls._layers.pop(key, None)

    @classmethod
    def get_layer(cls, config: dict[str, Any]) -> PromptOpsLayer:
        cfg = config if isinstance(config, dict) else {}
        key = _config_fingerprint(cfg)
        with cls._lock:
            layer = cls._layers.get(key)
            if layer is None:
                layer = PromptOpsLayer(cfg)
                cls._layers[key] = layer
            else:
                cls._layers.move_to_end(key)
            cls._evict_overflow_locked(cap=_service_cache_max_entries(cfg))
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
            else:
                cls._apis.move_to_end(key)
            cls._evict_overflow_locked(cap=_service_cache_max_entries(cfg))
            return api


def get_promptops_layer(config: dict[str, Any]) -> PromptOpsLayer:
    return PromptOpsService.get_layer(config)


def get_promptops_api(config: dict[str, Any]) -> Any:
    return PromptOpsService.get_api(config)
