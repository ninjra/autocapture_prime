#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.builder_jepa import JEPAStateBuilder
from autocapture_nx.state_layer.processor import StateTapeProcessor
from autocapture_nx.state_layer.store_sqlite import StateTapeStore


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _resolve_table(conn: sqlite3.Connection) -> tuple[str, str, str, str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('metadata','records')")
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("metadata_table_missing")
    table = str(row[0])
    cols = [str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    id_col = "id" if "id" in cols else ("record_id" if "record_id" in cols else "")
    payload_col = "payload" if "payload" in cols else ("payload_json" if "payload_json" in cols else "")
    record_type_col = "record_type" if "record_type" in cols else ""
    if not id_col or not payload_col or not record_type_col:
        raise RuntimeError("metadata_columns_missing")
    return table, id_col, payload_col, record_type_col


class _SqliteMetadataStore:
    def __init__(self, db_path: Path) -> None:
        self._path = Path(db_path)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._table, self._id_col, self._payload_col, self._record_type_col = _resolve_table(self._conn)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def get(self, record_id: str, default: Any = None) -> Any:
        row = self._conn.execute(
            f"SELECT {self._payload_col} FROM {self._table} WHERE {self._id_col} = ?",
            (str(record_id),),
        ).fetchone()
        if row is None:
            return default
        raw = row[0]
        if not isinstance(raw, str) or not raw.strip():
            return default
        try:
            parsed = json.loads(raw)
        except Exception:
            return default
        return parsed if isinstance(parsed, dict) else default

    def put(self, record_id: str, value: dict[str, Any]) -> None:
        payload = json.dumps(value, sort_keys=True)
        record_type = str(value.get("record_type") or "")
        ts_utc = str(value.get("ts_utc") or value.get("ts_start_utc") or value.get("ts_end_utc") or "")
        run_id = str(value.get("run_id") or "")
        cols = [self._id_col, self._record_type_col, "ts_utc", self._payload_col, "run_id"]
        vals = [str(record_id), record_type, ts_utc, payload, run_id]
        sql = f"INSERT OR REPLACE INTO {self._table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
        self._conn.execute(sql, tuple(vals))
        self._conn.commit()

    def put_new(self, record_id: str, value: dict[str, Any]) -> None:
        payload = json.dumps(value, sort_keys=True)
        record_type = str(value.get("record_type") or "")
        ts_utc = str(value.get("ts_utc") or value.get("ts_start_utc") or value.get("ts_end_utc") or "")
        run_id = str(value.get("run_id") or "")
        cols = [self._id_col, self._record_type_col, "ts_utc", self._payload_col, "run_id"]
        vals = [str(record_id), record_type, ts_utc, payload, run_id]
        sql = f"INSERT INTO {self._table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
        try:
            self._conn.execute(sql, tuple(vals))
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            raise FileExistsError(str(record_id)) from exc

    def put_replace(self, record_id: str, value: dict[str, Any]) -> None:
        self.put(record_id, value)

    def keys(self) -> list[str]:
        rows = self._conn.execute(f"SELECT {self._id_col} FROM {self._table} ORDER BY {self._id_col}").fetchall()
        return [str(row[0]) for row in rows]


class _Logger:
    def log(self, _event: str, _payload: dict[str, Any]) -> None:
        return


class _System:
    def __init__(self, config: dict[str, Any], caps: dict[str, Any]) -> None:
        self.config = config
        self._caps = dict(caps)

    def has(self, name: str) -> bool:
        return str(name) in self._caps

    def get(self, name: str) -> Any:
        return self._caps[str(name)]


def _count_state_tables(state_db_path: Path) -> dict[str, int]:
    if not state_db_path.exists():
        return {"state_span": 0, "state_edge": 0, "state_evidence_link": 0}
    conn = sqlite3.connect(str(state_db_path))
    try:
        counts: dict[str, int] = {}
        for table in ("state_span", "state_edge", "state_evidence_link"):
            row = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            exists = bool(row and int(row[0]) > 0)
            if not exists:
                counts[table] = 0
                continue
            c = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = int(c[0]) if c else 0
        return counts
    finally:
        conn.close()


def backfill_state_tape(
    metadata_db_path: Path,
    *,
    state_db_path: Path,
    max_loops: int = 500,
    max_states_per_run: int = 2000,
) -> dict[str, Any]:
    metadata = _SqliteMetadataStore(metadata_db_path)
    logger = _Logger()
    try:
        config: dict[str, Any] = {
            "processing": {
                "state_layer": {
                    "enabled": True,
                    "emit_frame_evidence": True,
                    "batch": {
                        "max_states_per_run": max(1, int(max_states_per_run)),
                        "overlap_states": 1,
                    },
                    "features": {
                        "index_enabled": False,
                        "workflow_enabled": False,
                        "anomaly_enabled": False,
                        "training_enabled": False,
                    },
                }
            }
        }
        state_store = StateTapeStore(state_db_path)
        context = PluginContext(
            config=config,
            get_capability=lambda _name: None,
            logger=lambda *_args, **_kwargs: None,
            rng=None,
            rng_seed=None,
            rng_seed_hex=None,
        )
        builder = JEPAStateBuilder("builtin.state.jepa_like", context)
        system = _System(
            config,
            {
                "storage.metadata": metadata,
                "storage.state_tape": state_store,
                "state.builder": builder,
                "observability.logger": logger,
            },
        )
        before = _count_state_tables(state_db_path)
        processor = StateTapeProcessor(system)
        total = {
            "states_scanned": 0,
            "states_processed": 0,
            "spans_inserted": 0,
            "edges_inserted": 0,
            "evidence_inserted": 0,
            "errors": 0,
        }
        loops = 0
        done = False
        for loops in range(1, max(1, int(max_loops)) + 1):
            done, stats = processor.process_step(budget_ms=0)
            row = asdict(stats)
            for key in total.keys():
                total[key] = int(total.get(key, 0) or 0) + int(row.get(key, 0) or 0)
            if done:
                break
        after = _count_state_tables(state_db_path)
        return {
            "ok": True,
            "done": bool(done),
            "loops": int(loops),
            "metadata_db": str(metadata_db_path),
            "state_db": str(state_db_path),
            "before": before,
            "after": after,
            "delta": {
                "state_span": int(after.get("state_span", 0) - before.get("state_span", 0)),
                "state_edge": int(after.get("state_edge", 0) - before.get("state_edge", 0)),
                "state_evidence_link": int(after.get("state_evidence_link", 0) - before.get("state_evidence_link", 0)),
            },
            "stats": total,
        }
    finally:
        metadata.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill state tape spans/edges from derived.sst.state records.")
    parser.add_argument("--db", default="/mnt/d/autocapture/metadata.db", help="Path to metadata DB")
    parser.add_argument("--state-db", default="/mnt/d/autocapture/state/state_tape.db", help="Path to state_tape DB")
    parser.add_argument("--max-loops", type=int, default=500, help="Maximum processor loops")
    parser.add_argument("--max-states-per-run", type=int, default=2000, help="Max states per process_step run")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    db_path = Path(str(args.db)).expanduser()
    state_db = Path(str(args.state_db)).expanduser()
    if not db_path.exists():
        print(json.dumps({"ok": False, "error": "db_not_found", "db": str(db_path)}, sort_keys=True))
        return 2
    try:
        summary = backfill_state_tape(
            db_path,
            state_db_path=state_db,
            max_loops=max(1, int(args.max_loops)),
            max_states_per_run=max(1, int(args.max_states_per_run)),
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}:{exc}"}, sort_keys=True))
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
