"""Capability provider helpers."""

from __future__ import annotations

from typing import Any, Iterable


def capability_providers(capability: Any | None, default_provider: str) -> list[tuple[str, Any]]:
    """Return (provider_id, provider) pairs for a capability."""
    if capability is None:
        return []
    target = capability
    if hasattr(target, "target"):
        target = getattr(target, "target")
    if hasattr(target, "items"):
        try:
            items = list(target.items())
        except Exception:
            items = []
        if items:
            return [(str(pid), provider) for pid, provider in items]

    provider_fn = None
    for attr in ("providers", "iter_providers", "list_providers"):
        if hasattr(capability, attr):
            candidate = getattr(capability, attr)
            if callable(candidate):
                provider_fn = candidate
                break
    if provider_fn is not None:
        try:
            raw = provider_fn()
        except Exception:
            raw = None
        normalized = _normalize_provider_list(raw, default_provider)
        if normalized:
            return normalized

    return [(default_provider, capability)]


def _normalize_provider_list(raw: Any, default_provider: str) -> list[tuple[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        items: Iterable[Any] = list(raw.items())
    elif isinstance(raw, (list, tuple)):
        items = raw
    else:
        return []
    out: list[tuple[str, Any]] = []
    for item in items:
        provider_id = None
        provider = None
        if isinstance(item, dict):
            provider_id = item.get("provider_id") or item.get("id") or default_provider
            provider = item.get("provider") or item.get("extractor") or item.get("capability")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            provider_id = item[0]
            provider = item[1]
        if provider is None:
            continue
        out.append((str(provider_id or default_provider), provider))
    return out
