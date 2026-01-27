"""Compliance and redaction for derived SST artifacts."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .utils import norm_text


PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("ipv6", re.compile(r"\b[0-9A-F]{0,4}:(?:[0-9A-F]{0,4}:){1,6}[0-9A-F]{0,4}\b", re.IGNORECASE)),
    ("hex", re.compile(r"\b[0-9A-Fa-f]{32,}\b")),
    ("jwt", re.compile(r"\b[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("api_key", re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b")),
)

RE_REDACTED = re.compile(r"\[REDACTED:[^]]+\]")


def redact_artifacts(
    *,
    state: dict[str, Any],
    delta_event: dict[str, Any] | None,
    action_event: dict[str, Any] | None,
    enabled: bool,
    denylist_app_hints: list[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, dict[str, int]]:
    metrics = {
        "redactions": 0,
        "dropped": 0,
    }
    if not enabled:
        return state, delta_event, action_event, metrics
    if _denylisted(state, denylist_app_hints):
        metrics["dropped"] = 1
        return None, None, None, metrics
    state = _redact_state(state, metrics)
    delta_event = _redact_delta(delta_event, metrics)
    action_event = _redact_action(action_event, metrics)
    return state, delta_event, action_event, metrics


def _denylisted(state: dict[str, Any], denylist: list[str]) -> bool:
    if not denylist:
        return False
    apps = [norm_text(a).casefold() for a in state.get("visible_apps", ())]
    deny = [norm_text(a).casefold() for a in denylist if a]
    for app in apps:
        for needle in deny:
            if needle and needle in app:
                return True
    return False


def _redact_state(state: dict[str, Any], metrics: dict[str, int]) -> dict[str, Any]:
    tokens = []
    for token in state.get("tokens", ()):
        text, count = _redact_text(str(token.get("text", "")))
        metrics["redactions"] += count
        norm, count_norm = _redact_text(str(token.get("norm_text", "")))
        metrics["redactions"] += count_norm
        tokens.append({**token, "text": text, "norm_text": norm})

    tables = []
    for table in state.get("tables", ()):
        tables.append(_redact_table(table, metrics))

    spreadsheets = []
    for sheet in state.get("spreadsheets", ()):
        spreadsheets.append(_redact_table(sheet, metrics))

    code_blocks = []
    for block in state.get("code_blocks", ()):
        text, count = _redact_text(str(block.get("text", "")))
        metrics["redactions"] += count
        lines = []
        for line in block.get("lines", ()):
            red, c = _redact_text(str(line))
            metrics["redactions"] += c
            lines.append(red)
        code_blocks.append({**block, "text": text, "lines": tuple(lines)})

    visible_apps = []
    for app in state.get("visible_apps", ()):
        red, count = _redact_text(str(app))
        metrics["redactions"] += count
        visible_apps.append(red)

    return {
        **state,
        "tokens": tuple(tokens),
        "tables": tuple(tables),
        "spreadsheets": tuple(spreadsheets),
        "code_blocks": tuple(code_blocks),
        "visible_apps": tuple(visible_apps),
    }


def _redact_table(table: dict[str, Any], metrics: dict[str, int]) -> dict[str, Any]:
    cells = []
    for cell in table.get("cells", ()):
        text, count = _redact_text(str(cell.get("text", "")))
        metrics["redactions"] += count
        norm, count_norm = _redact_text(str(cell.get("norm_text", "")))
        metrics["redactions"] += count_norm
        cells.append({**cell, "text": text, "norm_text": norm})
    csv_text, count_csv = _redact_text(str(table.get("csv", "")))
    metrics["redactions"] += count_csv
    return {**table, "cells": tuple(cells), "csv": csv_text}


def _redact_delta(delta_event: dict[str, Any] | None, metrics: dict[str, int]) -> dict[str, Any] | None:
    if not delta_event:
        return None
    changes = []
    for change in delta_event.get("changes", ()):
        detail = _redact_obj(change.get("detail", {}), metrics)
        changes.append({**change, "detail": detail})
    return {**delta_event, "changes": tuple(changes)}


def _redact_action(action_event: dict[str, Any] | None, metrics: dict[str, int]) -> dict[str, Any] | None:
    if not action_event:
        return None
    primary = {**action_event.get("primary", {})}
    primary["evidence"] = _redact_obj(primary.get("evidence", {}), metrics)
    alternatives = []
    for alt in action_event.get("alternatives", ()):
        alt = {**alt}
        alt["evidence"] = _redact_obj(alt.get("evidence", {}), metrics)
        alternatives.append(alt)
    return {**action_event, "primary": primary, "alternatives": tuple(alternatives)}


def _redact_obj(obj: Any, metrics: dict[str, int]) -> Any:
    if isinstance(obj, str):
        red, count = _redact_text(obj)
        metrics["redactions"] += count
        return red
    if isinstance(obj, dict):
        return {str(k): _redact_obj(v, metrics) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return tuple(_redact_obj(v, metrics) for v in obj)
    return obj


def _redact_text(text: str) -> tuple[str, int]:
    if not text:
        return text, 0
    if RE_REDACTED.search(text):
        return text, 0
    count = 0
    out = text
    for kind, pattern in PATTERNS:
        def repl(match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            token = match.group(0)
            digest = hashlib.sha256(token[:16].encode("utf-8")).hexdigest()[:12]
            return f"[REDACTED:{kind}:{digest}]"

        out = pattern.sub(repl, out)
    return out, count

