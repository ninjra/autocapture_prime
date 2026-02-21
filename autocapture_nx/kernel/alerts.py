"""Alert derivation from journal events and telemetry."""

from __future__ import annotations

from typing import Any


_DEFAULT_RULES = {
    "disk.pressure": {"severity": "warning", "title": "Disk pressure"},
    "disk.critical": {"severity": "critical", "title": "Disk critical"},
    "capture.drop": {"severity": "warning", "title": "Capture dropped"},
    "capture.degrade": {"severity": "warning", "title": "Capture degraded"},
    "capture.restore": {"severity": "info", "title": "Capture restored"},
    "capture.halt_disk": {"severity": "critical", "title": "CAPTURE HALTED: DISK LOW"},
    "capture.backend_fallback": {"severity": "warning", "title": "Capture backend fallback"},
    "capture.silence": {"severity": "critical", "title": "Capture silent while active"},
    "processing.watchdog.stalled": {"severity": "critical", "title": "Processing watchdog stalled"},
    "processing.watchdog.error": {"severity": "warning", "title": "Processing watchdog error"},
    "processing.watchdog.restore": {"severity": "info", "title": "Processing watchdog restored"},
}


def _rules(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    alerts_cfg = config.get("alerts", {}) if isinstance(config, dict) else {}
    rules = alerts_cfg.get("rules", {}) if isinstance(alerts_cfg, dict) else {}
    if not isinstance(rules, dict) or not rules:
        return dict(_DEFAULT_RULES)
    merged = dict(_DEFAULT_RULES)
    for key, value in rules.items():
        if not isinstance(value, dict):
            continue
        merged[str(key)] = dict(merged.get(str(key), {}), **value)
    return merged


def derive_alerts(config: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alerts_cfg = config.get("alerts", {}) if isinstance(config, dict) else {}
    if isinstance(alerts_cfg, dict) and not bool(alerts_cfg.get("enabled", True)):
        return []
    max_records = None
    if isinstance(alerts_cfg, dict):
        try:
            max_records = int(alerts_cfg.get("max_records", 0) or 0)
        except Exception:
            max_records = None
    if max_records and max_records > 0:
        events = events[-max_records:]
    rules = _rules(config)
    alerts: list[dict[str, Any]] = []
    for entry in events:
        if not isinstance(entry, dict):
            continue
        event_type = str(entry.get("event_type", ""))
        if not event_type:
            continue
        rule = rules.get(event_type)
        if not rule:
            continue
        alerts.append(
            {
                "alert_id": entry.get("event_id") or entry.get("sequence") or event_type,
                "event_type": event_type,
                "severity": rule.get("severity", "info"),
                "title": rule.get("title", event_type),
                "ts_utc": entry.get("ts_utc"),
                "payload": entry.get("payload", {}),
            }
        )
    return alerts
