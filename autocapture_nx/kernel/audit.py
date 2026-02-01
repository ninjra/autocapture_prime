"""Plugin execution audit logging."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.hashing import sha256_bytes, sha256_text


_DEF_SCHEMA = """
CREATE TABLE IF NOT EXISTS plugin_exec_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    run_id TEXT NOT NULL,
    plugin_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    method TEXT NOT NULL,
    ok INTEGER NOT NULL,
    error TEXT,
    duration_ms INTEGER,
    rows_read INTEGER,
    rows_written INTEGER,
    memory_rss_mb INTEGER,
    memory_vms_mb INTEGER,
    input_hash TEXT,
    output_hash TEXT,
    data_hash TEXT,
    code_hash TEXT,
    settings_hash TEXT,
    input_bytes INTEGER,
    output_bytes INTEGER
);
CREATE INDEX IF NOT EXISTS idx_plugin_exec_audit_plugin_id ON plugin_exec_audit(plugin_id);

CREATE TABLE IF NOT EXISTS plugin_registry_meta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    run_id TEXT NOT NULL,
    plugin_id TEXT NOT NULL,
    version TEXT,
    code_hash TEXT,
    settings_hash TEXT,
    capability_tags TEXT,
    provides TEXT,
    entrypoints TEXT,
    permissions TEXT,
    manifest_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_plugin_registry_meta_plugin_id ON plugin_registry_meta(plugin_id);

CREATE TABLE IF NOT EXISTS plugin_load_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    run_id TEXT NOT NULL,
    plugin_id TEXT,
    entrypoint TEXT,
    phase TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_plugin_load_errors_plugin_id ON plugin_load_errors(plugin_id);

CREATE TABLE IF NOT EXISTS template_mapping_diff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    run_id TEXT NOT NULL,
    mapping_id TEXT NOT NULL,
    mapping_kind TEXT NOT NULL,
    prev_hash TEXT,
    new_hash TEXT NOT NULL,
    diff TEXT,
    prev_sources TEXT,
    new_sources TEXT
);
CREATE INDEX IF NOT EXISTS idx_template_mapping_diff_mapping_id ON template_mapping_diff(mapping_id);
"""


class PluginAuditLog:
    def __init__(self, path: str | Path, *, run_id: str | None = None) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._run_id = run_id
        self._ensure_schema()

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "PluginAuditLog":
        storage = config.get("storage", {}) if isinstance(config, dict) else {}
        audit_path = storage.get("audit_db_path") or storage.get("audit_path") or "data/audit.db"
        run_id = ""
        if isinstance(config, dict):
            run_id = str(config.get("runtime", {}).get("run_id") or "")
        return cls(audit_path, run_id=run_id or None)

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        return self._conn

    def _ensure_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            conn.executescript(_DEF_SCHEMA)
            conn.commit()

    def record(
        self,
        *,
        run_id: str,
        plugin_id: str,
        capability: str,
        method: str,
        ok: bool,
        error: str | None,
        duration_ms: int | None,
        rows_read: int | None,
        rows_written: int | None,
        memory_rss_mb: int | None,
        memory_vms_mb: int | None,
        input_hash: str | None,
        output_hash: str | None,
        data_hash: str | None,
        code_hash: str | None,
        settings_hash: str | None,
        input_bytes: int | None,
        output_bytes: int | None,
    ) -> None:
        payload = (
            _utc_ts(),
            run_id,
            plugin_id,
            capability,
            method,
            1 if ok else 0,
            error,
            duration_ms,
            rows_read,
            rows_written,
            memory_rss_mb,
            memory_vms_mb,
            input_hash,
            output_hash,
            data_hash,
            code_hash,
            settings_hash,
            input_bytes,
            output_bytes,
        )
        with self._lock:
            conn = self._connect()
            conn.execute(
                """
                INSERT INTO plugin_exec_audit (
                    ts_utc, run_id, plugin_id, capability, method, ok, error,
                    duration_ms, rows_read, rows_written, memory_rss_mb, memory_vms_mb,
                    input_hash, output_hash, data_hash, code_hash, settings_hash,
                    input_bytes, output_bytes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            conn.commit()

    def failure_summary(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                """
                SELECT plugin_id,
                       SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS failures,
                       SUM(CASE WHEN ok = 1 THEN 1 ELSE 0 END) AS successes,
                       MAX(CASE WHEN ok = 0 THEN ts_utc ELSE NULL END) AS last_failure
                  FROM plugin_exec_audit
              GROUP BY plugin_id
                """
            ).fetchall()
        summary: dict[str, dict[str, Any]] = {}
        for plugin_id, failures, successes, last_failure in rows:
            summary[str(plugin_id)] = {
                "failures": int(failures or 0),
                "successes": int(successes or 0),
                "last_failure": str(last_failure) if last_failure else None,
            }
        return summary

    def record_plugin_metadata(
        self,
        *,
        plugin_id: str,
        version: str | None,
        code_hash: str | None,
        settings_hash: str | None,
        capability_tags: list[str] | None,
        provides: list[str] | None,
        entrypoints: list[dict[str, Any]] | None,
        permissions: dict[str, Any] | None,
        manifest_path: str | None,
        run_id: str | None = None,
    ) -> None:
        run_id = run_id or self._run_id or "run"
        payload = (
            _utc_ts(),
            run_id,
            plugin_id,
            version,
            code_hash,
            settings_hash,
            _json_dump(capability_tags),
            _json_dump(provides),
            _json_dump(entrypoints),
            _json_dump(permissions),
            manifest_path,
        )
        with self._lock:
            conn = self._connect()
            conn.execute(
                """
                INSERT INTO plugin_registry_meta (
                    ts_utc, run_id, plugin_id, version, code_hash, settings_hash,
                    capability_tags, provides, entrypoints, permissions, manifest_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            conn.commit()

    def record_load_failure(
        self,
        *,
        plugin_id: str | None,
        entrypoint: str | None,
        phase: str | None,
        error: str,
        run_id: str | None = None,
    ) -> None:
        run_id = run_id or self._run_id or "run"
        payload = (
            _utc_ts(),
            run_id,
            plugin_id,
            entrypoint,
            phase,
            error,
        )
        with self._lock:
            conn = self._connect()
            conn.execute(
                """
                INSERT INTO plugin_load_errors (
                    ts_utc, run_id, plugin_id, entrypoint, phase, error
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            conn.commit()

    def record_template_diff(
        self,
        *,
        mapping_id: str,
        mapping_kind: str,
        sources: list[dict[str, Any]],
        combined_hash: str | None,
        run_id: str | None = None,
    ) -> bool:
        run_id = run_id or self._run_id or "run"
        prev = self._latest_template_mapping(mapping_id, mapping_kind)
        prev_hash = prev.get("new_hash") if prev else None
        new_hash = combined_hash or ""
        if prev_hash and new_hash and prev_hash == new_hash:
            return False
        prev_sources = prev.get("new_sources") if prev else None
        new_sources = _stable_sources_json(sources)
        diff = _unified_diff(prev_sources or "", new_sources)
        payload = (
            _utc_ts(),
            run_id,
            mapping_id,
            mapping_kind,
            prev_hash,
            new_hash,
            diff,
            prev_sources,
            new_sources,
        )
        with self._lock:
            conn = self._connect()
            conn.execute(
                """
                INSERT INTO template_mapping_diff (
                    ts_utc, run_id, mapping_id, mapping_kind, prev_hash, new_hash,
                    diff, prev_sources, new_sources
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            conn.commit()
        return True

    def _latest_template_mapping(self, mapping_id: str, mapping_kind: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                """
                SELECT new_hash, new_sources
                  FROM template_mapping_diff
                 WHERE mapping_id = ? AND mapping_kind = ?
              ORDER BY id DESC
                 LIMIT 1
                """,
                (mapping_id, mapping_kind),
            ).fetchone()
        if not row:
            return None
        return {"new_hash": row[0], "new_sources": row[1]}


def _utc_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _json_dump(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    except Exception:
        return None


def _stable_sources_json(sources: list[dict[str, Any]]) -> str:
    ordered = sorted(
        sources,
        key=lambda item: (
            str(item.get("source_id") or ""),
            str(item.get("path") or ""),
            str(item.get("kind") or ""),
        ),
    )
    return json.dumps(ordered, sort_keys=True, ensure_ascii=True, indent=2)


def _unified_diff(before: str, after: str) -> str:
    import difflib

    before_lines = (before or "").splitlines(keepends=True)
    after_lines = (after or "").splitlines(keepends=True)
    diff = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile="a/mapping.json",
        tofile="b/mapping.json",
    )
    return "".join(diff)


def _normalize(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (str, int, bool)):
        return obj
    if isinstance(obj, float):
        return repr(obj)
    if isinstance(obj, bytes):
        return {"__bytes_sha256": sha256_bytes(obj), "__bytes_len": len(obj)}
    if isinstance(obj, Path):
        return str(obj)
    if is_dataclass(obj):
        if isinstance(obj, type):
            return str(obj)
        return _normalize(asdict(obj))
    if isinstance(obj, dict):
        normalized: dict[str, Any] = {}
        for key in sorted(obj.keys(), key=lambda k: str(k)):
            normalized[str(key)] = _normalize(obj[key])
        return normalized
    if isinstance(obj, (list, tuple)):
        return [_normalize(item) for item in obj]
    if isinstance(obj, set):
        return sorted([_normalize(item) for item in obj], key=lambda v: str(v))
    return str(obj)


_AUDIT_LOG_PATH = Path("artifacts") / "audit" / "audit.jsonl"


def append_audit_event(
    *,
    action: str,
    actor: str,
    outcome: str,
    details: Any | None = None,
    log_path: str | Path | None = None,
) -> None:
    """Append a privileged-action audit record to JSONL (append-only)."""
    payload = {
        "schema_version": 1,
        "ts_utc": _utc_ts(),
        "action": str(action),
        "actor": str(actor),
        "outcome": str(outcome),
        "details": _normalize(details),
    }
    path = Path(log_path) if log_path is not None else _AUDIT_LOG_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        return


def hash_payload(obj: Any) -> tuple[str | None, int | None]:
    try:
        normalized = _normalize(obj)
        dumped = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return sha256_text(dumped), len(dumped.encode("utf-8"))
    except Exception:
        return None, None


def estimate_rows_written(method: str, args: list[Any], kwargs: dict[str, Any]) -> int | None:
    method_name = str(method or "").lower()
    if method_name in {"put", "put_new", "put_replace", "delete", "remove"}:
        return 1
    if method_name in {"put_batch", "put_many", "insert_many"}:
        if args and isinstance(args[0], (list, tuple)):
            return len(args[0])
    if "batch" in method_name and args and isinstance(args[0], (list, tuple)):
        return len(args[0])
    return None


def estimate_rows_read(method: str, result: Any) -> int | None:
    method_name = str(method or "").lower()
    if method_name in {"get", "fetch", "load"}:
        return 1 if result is not None else 0
    if isinstance(result, (list, tuple)):
        return len(result)
    if isinstance(result, dict):
        for key in ("records", "items", "rows", "results"):
            value = result.get(key)
            if isinstance(value, (list, tuple)):
                return len(value)
    return None
