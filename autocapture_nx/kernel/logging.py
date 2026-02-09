"""Structured JSONL logging with correlation IDs (OPS-01).

Design goals:
- Lightweight: no heavy deps, no background threads by default.
- Deterministic-ish: stable key ordering in JSON serialization.
- Archive-only rotation: never delete local logs (AGENTS non-negotiable).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.redaction import redact_obj


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


@dataclass(frozen=True)
class JsonlLoggerConfig:
    path: Path
    rotate_max_bytes: int


class JsonlLogger:
    def __init__(self, cfg: JsonlLoggerConfig) -> None:
        self._cfg = cfg
        self._cfg.path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_config(cls, config: dict[str, Any], *, name: str = "core") -> "JsonlLogger":
        storage = config.get("storage", {}) if isinstance(config, dict) else {}
        data_dir = Path(str(storage.get("data_dir", "data")))
        logs_dir = data_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        path = logs_dir / f"{name}.jsonl"
        rotate_max_bytes = _safe_int(storage.get("log_rotate_max_bytes", 5_000_000), 5_000_000)
        return cls(JsonlLoggerConfig(path=path, rotate_max_bytes=max(1024, rotate_max_bytes)))

    @property
    def path(self) -> str:
        return str(self._cfg.path)

    def _rotate_if_needed(self) -> None:
        try:
            if not self._cfg.path.exists():
                return
            size = self._cfg.path.stat().st_size
            if size < self._cfg.rotate_max_bytes:
                return
        except Exception:
            return
        # Archive-only rotation: rename current file into logs/archive/.
        try:
            archive_dir = self._cfg.path.parent / "archive"
            archive_dir.mkdir(parents=True, exist_ok=True)
            ts = _utc_now_iso().replace(":", "").replace("-", "").replace(".", "")
            archived = archive_dir / f"{self._cfg.path.stem}.{ts}{self._cfg.path.suffix}"
            if not archived.exists():
                self._cfg.path.replace(archived)
        except Exception:
            return

    def event(
        self,
        *,
        event: str,
        run_id: str | None = None,
        job_id: str | None = None,
        plugin_id: str | None = None,
        level: str = "info",
        ts_utc: str | None = None,
        **fields: Any,
    ) -> None:
        payload: dict[str, Any] = {
            "ts_utc": str(ts_utc or _utc_now_iso()),
            "level": str(level or "info"),
            "event": str(event or "event"),
            "run_id": str(run_id or ""),
            "job_id": str(job_id or ""),
            "plugin_id": str(plugin_id or ""),
        }
        for k, v in fields.items():
            if k in payload:
                continue
            payload[str(k)] = v
        # SEC-09: redact secrets in logs at export boundary.
        line = json.dumps(redact_obj(payload), sort_keys=True)
        self._rotate_if_needed()
        try:
            with self._cfg.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            return
