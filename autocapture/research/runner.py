"""Research runner orchestrating sources + watchlists."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from autocapture.plugins.manager import PluginManager
from autocapture.research.cache import ResearchCache
from autocapture.research.scout import ResearchScout, ResearchSource, Watchlist


def _data_root(config: dict[str, Any]) -> Path:
    paths = config.get("paths", {}) if isinstance(config, dict) else {}
    data_dir = paths.get("data_dir") or config.get("storage", {}).get("data_dir", "data")
    return Path(data_dir)


class ResearchRunner:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._manager = PluginManager(config, safe_mode=bool(config.get("plugins", {}).get("safe_mode", False)))

    def _cfg(self) -> dict[str, Any]:
        return self._config.get("research", {}) if isinstance(self._config, dict) else {}

    def _watchlist(self) -> Watchlist:
        cfg = self._cfg()
        tags = list(cfg.get("watchlist", {}).get("tags", []))
        try:
            ext = self._manager.get_extension("research.watchlist", name=str(cfg.get("watchlist_name", "default")))
            watchlist = ext.instance
        except Exception:
            watchlist = Watchlist(tags=[])
        watchlist.tags = tags
        return watchlist

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
        try:
            ext = self._manager.get_extension("research.source", name=str(cfg.get("source_name", "default")))
            return [ext.instance]
        except Exception:
            return [ResearchSource(source_id="default", items=[])]

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


def _safe_json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True)
