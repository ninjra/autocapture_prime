"""Research runner orchestrating sources + watchlists."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
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
        self._checkpoint_loaded = False
        self._cursor_index = 0

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
