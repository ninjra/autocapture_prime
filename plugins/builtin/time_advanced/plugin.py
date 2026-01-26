"""Deterministic time intent parser plugin with timezone handling."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from zoneinfo import ZoneInfo

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?\b")
LAST_RE = re.compile(r"\b(last|past)\s+(\d+)\s+(minute|minutes|hour|hours|day|days)\b")
BETWEEN_RE = re.compile(r"\b(?:between|from)\s+(\d{4}-\d{2}-\d{2})\s+(?:and|to)\s+(\d{4}-\d{2}-\d{2})\b")


class TimeIntentParser(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"time.intent_parser": self}

    def _tz(self):
        tz_name = self.context.config.get("time", {}).get("timezone") or self.context.config.get("runtime", {}).get("timezone", "UTC")
        try:
            return ZoneInfo(tz_name)
        except Exception:
            try:
                return ZoneInfo("UTC")
            except Exception:
                return timezone.utc

    def _tie_breaker_fold(self) -> int:
        tie = self.context.config.get("time", {}).get("dst_tie_breaker", "earliest")
        return 0 if tie == "earliest" else 1

    def _localize(self, naive: datetime) -> datetime:
        tz = self._tz()
        fold = self._tie_breaker_fold()
        return naive.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc)

    def parse(self, text: str, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        tz = self._tz()
        now_local = now.astimezone(tz)
        tz_name = getattr(tz, "key", None) or tz.tzname(None) or "UTC"
        assumptions: list[str] = []
        if tz_name == "UTC" and self.context.config.get("time", {}).get("timezone") not in (None, "UTC"):
            assumptions.append("timezone_fallback_utc")
        lowered = text.lower()

        if "today" in lowered:
            start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            end_local = start_local + timedelta(days=1)
            return {
                "query": text,
                "time_window": {
                    "start": start_local.astimezone(timezone.utc).isoformat(),
                    "end": end_local.astimezone(timezone.utc).isoformat(),
                },
                "tz": tz_name,
                "assumptions": assumptions,
            }
        if "yesterday" in lowered:
            end_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            start_local = end_local - timedelta(days=1)
            return {
                "query": text,
                "time_window": {
                    "start": start_local.astimezone(timezone.utc).isoformat(),
                    "end": end_local.astimezone(timezone.utc).isoformat(),
                },
                "tz": tz_name,
                "assumptions": assumptions,
            }
        if "tomorrow" in lowered:
            start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            end_local = start_local + timedelta(days=1)
            return {
                "query": text,
                "time_window": {
                    "start": start_local.astimezone(timezone.utc).isoformat(),
                    "end": end_local.astimezone(timezone.utc).isoformat(),
                },
                "tz": tz_name,
                "assumptions": assumptions,
            }

        between = BETWEEN_RE.search(lowered)
        if between:
            start_date = datetime.fromisoformat(between.group(1))
            end_date = datetime.fromisoformat(between.group(2)) + timedelta(days=1)
            start_utc = self._localize(start_date)
            end_utc = self._localize(end_date)
            assumptions.append("between_dates_inclusive")
            return {
                "query": text,
                "time_window": {"start": start_utc.isoformat(), "end": end_utc.isoformat()},
                "tz": tz_name,
                "assumptions": assumptions,
            }

        rel = LAST_RE.search(lowered)
        if rel:
            qty = int(rel.group(2))
            unit = rel.group(3)
            delta = timedelta(minutes=qty) if "minute" in unit else timedelta(hours=qty) if "hour" in unit else timedelta(days=qty)
            start = now - delta
            return {
                "query": text,
                "time_window": {"start": start.isoformat(), "end": now.isoformat()},
                "tz": tz_name,
                "assumptions": assumptions,
            }

        date_match = DATE_RE.search(lowered)
        if date_match:
            year, month, day = map(int, date_match.group(1, 2, 3))
            hour = int(date_match.group(4) or 0)
            minute = int(date_match.group(5) or 0)
            naive = datetime(year, month, day, hour, minute)
            start_utc = self._localize(naive)
            if date_match.group(4) is None:
                end_utc = start_utc + timedelta(days=1)
                assumptions.append("date_interpreted_as_full_day")
            else:
                end_utc = start_utc + timedelta(hours=1)
                assumptions.append("time_window_default_1h")
            return {
                "query": text,
                "time_window": {"start": start_utc.isoformat(), "end": end_utc.isoformat()},
                "tz": tz_name,
                "assumptions": assumptions,
            }

        return {"query": text, "time_window": None, "tz": tz_name, "assumptions": assumptions}


def create_plugin(plugin_id: str, context: PluginContext) -> TimeIntentParser:
    return TimeIntentParser(plugin_id, context)
