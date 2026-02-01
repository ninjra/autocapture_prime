"""Research runner orchestrating sources + watchlists."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Iterable

from autocapture_nx.plugin_system.registry import PluginRegistry
from autocapture.research.cache import ResearchCache
from autocapture.research.scout import ResearchScout, ResearchSource, Watchlist


def _data_root(config: dict[str, Any]) -> Path:
    paths = config.get("paths", {}) if isinstance(config, dict) else {}
    data_dir = paths.get("data_dir") or config.get("storage", {}).get("data_dir", "data")
    return Path(data_dir)


def _resolve_plugin_id(name: str | None, *, prefix: str) -> str:
    if not name:
        return ""
    value = str(name).strip()
    if not value:
        return ""
    if "." in value:
        return value
    return f"{prefix}{value}"


def _scoped_plugin_config(config: dict[str, Any], plugin_ids: list[str]) -> dict[str, Any]:
    scoped = deepcopy(config) if isinstance(config, dict) else {}
    plugins_cfg = scoped.setdefault("plugins", {})
    plugins_cfg["allowlist"] = list(plugin_ids)
    plugins_cfg["enabled"] = {pid: True for pid in plugin_ids}
    plugins_cfg["default_pack"] = list(plugin_ids)
    return scoped


class _SourceAdapter:
    def __init__(self, source: Any, source_id: str) -> None:
        self._source = source
        self.source_id = source_id

    def fetch(self) -> list[dict[str, Any]]:
        return self._source.fetch()


class _WatchlistAdapter:
    def __init__(self, watchlist: Any, tags: list[str]) -> None:
        self._watchlist = watchlist
        self.tags = list(tags)
        self._apply_tags()

    def _apply_tags(self) -> None:
        setter = getattr(self._watchlist, "set_tags", None)
        if callable(setter):
            try:
                setter(list(self.tags))
                return
            except Exception:
                pass
        try:
            self._watchlist.tags = list(self.tags)
        except Exception:
            return

    def filter_items(self, items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            return self._watchlist.filter_items(items)
        except Exception:
            return list(items)


def _source_id_for(source: Any, fallback: str) -> str:
    try:
        value = getattr(source, "source_id", None)
    except Exception:
        value = None
    if isinstance(value, str) and value:
        return value
    if callable(value):
        try:
            result = value()
            if isinstance(result, dict):
                result = result.get("source_id")
            if result:
                return str(result)
        except Exception:
            pass
    for method in ("get_source_id", "describe"):
        try:
            attr = getattr(source, method, None)
        except Exception:
            attr = None
        if not callable(attr):
            continue
        try:
            result = attr()
        except Exception:
            continue
        if isinstance(result, dict):
            result = result.get("source_id")
        if result:
            return str(result)
    return fallback


class ResearchRunner:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._plugins: list[Any] = []
        self._capabilities: Any | None = None
        self._plugin_ids: tuple[str, ...] = tuple()
        self._checkpoint_loaded = False
        self._cursor_index = 0

    def _cfg(self) -> dict[str, Any]:
        return self._config.get("research", {}) if isinstance(self._config, dict) else {}

    def _research_plugin_ids(self) -> list[str]:
        cfg = self._cfg()
        source_name = cfg.get("source_name", "default")
        watch_name = cfg.get("watchlist_name", "default")
        ids: list[str] = []
        source_id = _resolve_plugin_id(source_name, prefix="builtin.research.")
        watch_id = _resolve_plugin_id(watch_name, prefix="builtin.research.")
        if source_id:
            ids.append(source_id)
        if watch_id and watch_id not in ids:
            ids.append(watch_id)
        return ids

    def _ensure_plugins(self) -> None:
        plugin_ids = tuple(self._research_plugin_ids())
        if plugin_ids == self._plugin_ids and self._capabilities is not None:
            return
        self._plugin_ids = plugin_ids
        self._plugins = []
        self._capabilities = None
        if not plugin_ids:
            return
        try:
            scoped = _scoped_plugin_config(self._config, list(plugin_ids))
            registry = PluginRegistry(scoped, safe_mode=bool(scoped.get("plugins", {}).get("safe_mode", False)))
            plugins, caps = registry.load_plugins()
            self._plugins = plugins
            self._capabilities = caps
        except Exception:
            self._plugins = []
            self._capabilities = None

    def _plugin_capability(self, plugin_id: str, capability: str) -> Any | None:
        for plugin in self._plugins:
            if plugin.plugin_id != plugin_id:
                continue
            if isinstance(plugin.capabilities, dict):
                cap = plugin.capabilities.get(capability)
                if cap is not None:
                    return cap
        return None

    def _watchlist(self) -> Watchlist:
        cfg = self._cfg()
        tags = list(cfg.get("watchlist", {}).get("tags", []))
        self._ensure_plugins()
        watchlist = None
        watch_id = _resolve_plugin_id(cfg.get("watchlist_name", "default"), prefix="builtin.research.")
        if watch_id:
            watchlist = self._plugin_capability(watch_id, "research.watchlist")
        if watchlist is None and self._capabilities is not None:
            try:
                watchlist = self._capabilities.get("research.watchlist")
            except Exception:
                watchlist = None
        if watchlist is None:
            return Watchlist(tags=tags)
        return _WatchlistAdapter(watchlist, tags)

    def _sources_from_config(self, items: Iterable[dict[str, Any]]) -> list[ResearchSource]:
        sources: list[ResearchSource] = []
        for entry in items:
            if not isinstance(entry, dict):
                continue
            source_id = str(entry.get("source_id") or entry.get("id") or "source")
            records = list(entry.get("items", []))
            sources.append(ResearchSource(source_id=source_id, items=records))
        return sources

    def _sources(self) -> list[ResearchSource]:
        cfg = self._cfg()
        configured = cfg.get("sources", [])
        if isinstance(configured, list) and configured:
            return self._sources_from_config(configured)
        self._ensure_plugins()
        source = None
        source_id = _resolve_plugin_id(cfg.get("source_name", "default"), prefix="builtin.research.")
        if source_id:
            source = self._plugin_capability(source_id, "research.source")
        if source is None and self._capabilities is not None:
            try:
                source = self._capabilities.get("research.source")
            except Exception:
                source = None
        if source is None:
            return [ResearchSource(source_id="default", items=[])]
        resolved_id = _source_id_for(source, source_id or "default")
        return [_SourceAdapter(source, resolved_id)]

    def _checkpoint_path(self) -> Path:
        cfg = self._cfg()
        root = _data_root(self._config)
        return Path(cfg.get("checkpoint_path") or root / "research" / "checkpoint.json")

    def _load_checkpoint(self) -> None:
        if self._checkpoint_loaded:
            return
        self._checkpoint_loaded = True
        path = self._checkpoint_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        idx = data.get("cursor_index")
        try:
            self._cursor_index = int(idx or 0)
        except Exception:
            self._cursor_index = 0

    def _store_checkpoint(self) -> None:
        path = self._checkpoint_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cursor_index": int(self._cursor_index),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        path.write_text(_safe_json(payload), encoding="utf-8")

    def run_once(self) -> dict[str, Any]:
        cfg = self._cfg()
        if not bool(cfg.get("enabled", True)):
            return {"ok": False, "reason": "disabled"}
        watchlist = self._watchlist()
        sources = self._sources()
        root = _data_root(self._config)
        cache_dir = Path(cfg.get("cache_dir") or root / "research" / "cache")
        report_dir = Path(cfg.get("report_dir") or root / "research" / "reports")
        cache = ResearchCache(cache_dir)
        threshold = cfg.get("threshold")
        if threshold is None:
            pct = int(cfg.get("threshold_pct", 10))
            threshold = max(0.0, min(1.0, pct / 100.0))
        else:
            threshold = float(threshold)

        reports: list[dict[str, Any]] = []
        for source in sources:
            scout = ResearchScout(source, watchlist, cache)
            reports.append(scout.run(threshold=threshold))

        payload = {
            "ok": True,
            "reports": reports,
            "ran_at": datetime.now(timezone.utc).isoformat(),
        }
        if report_dir:
            report_dir.mkdir(parents=True, exist_ok=True)
            name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ.json")
            (report_dir / name).write_text(_safe_json(payload), encoding="utf-8")
        return payload

    def run_step(self, *, should_abort=None, budget_ms: int = 0) -> bool:
        cfg = self._cfg()
        if not bool(cfg.get("enabled", True)):
            return True
        self._load_checkpoint()
        sources = self._sources()
        if not sources:
            return True
        if self._cursor_index >= len(sources):
            self._cursor_index = 0

        start_mono = time.monotonic()
        deadline = None
        if budget_ms and budget_ms > 0:
            deadline = start_mono + (budget_ms / 1000.0)
        if should_abort and should_abort():
            return False

        watchlist = self._watchlist()
        root = _data_root(self._config)
        cache_dir = Path(cfg.get("cache_dir") or root / "research" / "cache")
        report_dir = Path(cfg.get("report_dir") or root / "research" / "reports")
        cache = ResearchCache(cache_dir)
        threshold = cfg.get("threshold")
        if threshold is None:
            pct = int(cfg.get("threshold_pct", 10))
            threshold = max(0.0, min(1.0, pct / 100.0))
        else:
            threshold = float(threshold)

        source = sources[self._cursor_index]
        scout = ResearchScout(source, watchlist, cache)
        report = scout.run(threshold=threshold)
        payload = {
            "ok": True,
            "reports": [report],
            "ran_at": datetime.now(timezone.utc).isoformat(),
        }
        if report_dir:
            report_dir.mkdir(parents=True, exist_ok=True)
            name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ.step.json")
            (report_dir / name).write_text(_safe_json(payload), encoding="utf-8")

        self._cursor_index += 1
        done = self._cursor_index >= len(sources)
        self._store_checkpoint()
        if should_abort and should_abort():
            return False
        if deadline is not None and time.monotonic() >= deadline and not done:
            return False
        return done


def _safe_json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True)
