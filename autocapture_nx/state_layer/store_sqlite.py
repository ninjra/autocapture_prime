"""SQLite-backed state tape store (append-only)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable

from autocapture_nx.kernel.hashing import sha256_text
from .contracts import validate_state_edge, validate_state_span
from .ids import b64decode, b64encode, compute_embedding_hash


_SCHEMA = """
CREATE TABLE IF NOT EXISTS state_span (
  state_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  ts_start_ms INTEGER NOT NULL,
  ts_end_ms INTEGER NOT NULL,
  z_embedding BLOB NOT NULL,
  z_dim INTEGER NOT NULL,
  z_dtype TEXT NOT NULL,
  app TEXT,
  window_title_hash TEXT,
  top_entities_json TEXT,
  provenance_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state_edge (
  edge_id TEXT PRIMARY KEY,
  from_state_id TEXT NOT NULL,
  to_state_id TEXT NOT NULL,
  delta_embedding BLOB NOT NULL,
  delta_dim INTEGER NOT NULL,
  delta_dtype TEXT NOT NULL,
  pred_error REAL NOT NULL,
  provenance_json TEXT NOT NULL,
  FOREIGN KEY(from_state_id) REFERENCES state_span(state_id),
  FOREIGN KEY(to_state_id) REFERENCES state_span(state_id)
);

CREATE TABLE IF NOT EXISTS state_evidence_link (
  id TEXT PRIMARY KEY,
  state_object_type TEXT NOT NULL,
  state_object_id TEXT NOT NULL,
  evidence_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_state_span_time ON state_span(ts_start_ms, ts_end_ms);
CREATE INDEX IF NOT EXISTS idx_state_span_session ON state_span(session_id);
CREATE INDEX IF NOT EXISTS idx_state_edge_from_to ON state_edge(from_state_id, to_state_id);
"""


@dataclass
class StateTapeCounts:
    spans_inserted: int = 0
    edges_inserted: int = 0
    evidence_inserted: int = 0


def _normalize_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"__bytes_len": len(value), "__bytes_sha256": sha256_text(value.hex())}
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize_json(asdict(value))
    if isinstance(value, dict):
        return {str(key): _normalize_json(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_json(item) for item in value]
    return str(value)


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return json.dumps(_normalize_json(value), sort_keys=True)


class StateTapeStore:
    def __init__(
        self,
        db_path: str | Path,
        *,
        key: bytes | None = None,
        fsync_policy: str = "none",
    ) -> None:
        self._path = Path(db_path)
        self._key = key
        self._fsync_policy = str(fsync_policy or "none").lower()
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._key is None:
            conn = sqlite3.connect(str(self._path), check_same_thread=False)
        else:
            import sqlcipher3

            conn = sqlcipher3.connect(str(self._path), check_same_thread=False)
            # sqlcipher3 does not support parameter binding for PRAGMA key.
            conn.execute(f"PRAGMA key = \"x'{self._key.hex()}'\"")
        if self._fsync_policy == "critical":
            conn.execute("PRAGMA synchronous = FULL")
        elif self._fsync_policy == "bulk":
            conn.execute("PRAGMA synchronous = NORMAL")
        elif self._fsync_policy == "none":
            conn.execute("PRAGMA synchronous = OFF")
        return conn

    def _ensure(self) -> None:
        if self._conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = self._connect()
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def insert_batch(self, spans: list[dict[str, Any]], edges: list[dict[str, Any]]) -> StateTapeCounts:
        self._ensure()
        counts = StateTapeCounts()
        spans = spans or []
        edges = edges or []
        if not spans and not edges:
            return counts
        conn = self._conn
        if conn is None:
            return counts
        conn.execute("BEGIN")
        try:
            for span in spans:
                if not isinstance(span, dict):
                    continue
                # Normalize dataclasses/paths/bytes into JSON-safe structures
                # before schema validation and persistence.
                span_norm = _normalize_json(span)
                if not isinstance(span_norm, dict):
                    continue
                validate_state_span(span_norm)
                inserted = self._insert_span(conn, span_norm)
                if inserted:
                    counts.spans_inserted += 1
                    counts.evidence_inserted += self._insert_evidence_links(conn, "span", span_norm)
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                edge_norm = _normalize_json(edge)
                if not isinstance(edge_norm, dict):
                    continue
                validate_state_edge(edge_norm)
                inserted = self._insert_edge(conn, edge_norm)
                if inserted:
                    counts.edges_inserted += 1
                    counts.evidence_inserted += self._insert_evidence_links(conn, "edge", edge_norm)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return counts

    def _embedding_blob(self, embedding: dict[str, Any]) -> bytes:
        blob = embedding.get("blob")
        if isinstance(blob, str):
            return b64decode(blob)
        if isinstance(blob, (bytes, bytearray)):
            return bytes(blob)
        return b""

    def _insert_span(self, conn: sqlite3.Connection, span: dict[str, Any]) -> bool:
        emb = span.get("z_embedding", {}) if isinstance(span.get("z_embedding"), dict) else {}
        summary = span.get("summary_features", {}) if isinstance(span.get("summary_features"), dict) else {}
        top_entities = summary.get("top_entities", []) if isinstance(summary.get("top_entities"), list) else []
        payload = (
            span.get("state_id"),
            span.get("session_id"),
            int(span.get("ts_start_ms", 0)),
            int(span.get("ts_end_ms", 0)),
            self._embedding_blob(emb),
            int(emb.get("dim", 0) or 0),
            str(emb.get("dtype", "")),
            str(summary.get("app", "")) if summary.get("app") is not None else None,
            str(summary.get("window_title_hash", "")) if summary.get("window_title_hash") is not None else None,
            _json_dumps(top_entities),
            _json_dumps(span.get("provenance", {})),
        )
        try:
            conn.execute(
                """
                INSERT INTO state_span (
                    state_id, session_id, ts_start_ms, ts_end_ms,
                    z_embedding, z_dim, z_dtype,
                    app, window_title_hash, top_entities_json, provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def _insert_edge(self, conn: sqlite3.Connection, edge: dict[str, Any]) -> bool:
        emb = edge.get("delta_embedding", {}) if isinstance(edge.get("delta_embedding"), dict) else {}
        payload = (
            edge.get("edge_id"),
            edge.get("from_state_id"),
            edge.get("to_state_id"),
            self._embedding_blob(emb),
            int(emb.get("dim", 0) or 0),
            str(emb.get("dtype", "")),
            float(edge.get("pred_error", 0.0)),
            _json_dumps(edge.get("provenance", {})),
        )
        try:
            conn.execute(
                """
                INSERT INTO state_edge (
                    edge_id, from_state_id, to_state_id,
                    delta_embedding, delta_dim, delta_dtype,
                    pred_error, provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def _insert_evidence_links(self, conn: sqlite3.Connection, obj_type: str, obj: dict[str, Any]) -> int:
        evidence = obj.get("evidence", [])
        if not isinstance(evidence, list):
            return 0
        inserted = 0
        for ref in evidence:
            if not isinstance(ref, dict):
                continue
            media_id = str(ref.get("media_id", ""))
            ts_start = int(ref.get("ts_start_ms", 0) or 0)
            ts_end = int(ref.get("ts_end_ms", 0) or 0)
            link_id = sha256_text(f"{obj_type}:{obj.get('state_id') or obj.get('edge_id')}:{media_id}:{ts_start}:{ts_end}")
            try:
                conn.execute(
                    "INSERT INTO state_evidence_link (id, state_object_type, state_object_id, evidence_json) VALUES (?, ?, ?, ?)",
                    (
                        link_id,
                        obj_type,
                        obj.get("state_id") if obj_type == "span" else obj.get("edge_id"),
                    _json_dumps(ref),
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                continue
        return inserted

    def _fetch_evidence(self, obj_type: str, obj_ids: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
        self._ensure()
        conn = self._conn
        result: dict[str, list[dict[str, Any]]] = {str(obj_id): [] for obj_id in obj_ids}
        if conn is None or not obj_ids:
            return result
        ids = list(obj_ids)
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT state_object_id, evidence_json FROM state_evidence_link WHERE state_object_type = ? AND state_object_id IN ({placeholders})",
            (obj_type, *ids),
        ).fetchall()
        for obj_id, evidence_json in rows:
            try:
                payload = json.loads(evidence_json)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                result.setdefault(str(obj_id), []).append(payload)
        return result

    def get_snapshot_marker(self) -> dict[str, Any]:
        self._ensure()
        conn = self._conn
        if conn is None:
            return {
                "span_count": 0,
                "max_ts_end_ms": 0,
                "latest_state_id": "",
                "latest_embedding_hash": "",
                "latest_model_version": "",
            }
        row = conn.execute("SELECT COUNT(*), MAX(ts_end_ms) FROM state_span").fetchone()
        span_count = int(row[0] or 0)
        max_ts_end = int(row[1] or 0)
        latest = conn.execute(
            "SELECT state_id, z_embedding, provenance_json FROM state_span ORDER BY ts_end_ms DESC, state_id DESC LIMIT 1"
        ).fetchone()
        latest_state_id = ""
        latest_embedding_hash = ""
        latest_model_version = ""
        if latest:
            latest_state_id = str(latest[0] or "")
            emb_blob = latest[1] if latest[1] is not None else b""
            if isinstance(emb_blob, (bytes, bytearray)):
                latest_embedding_hash = compute_embedding_hash(bytes(emb_blob))
            provenance: dict[str, Any] = {}
            try:
                provenance = json.loads(latest[2]) if latest[2] else {}
            except Exception:
                provenance = {}
            if isinstance(provenance, dict):
                latest_model_version = str(provenance.get("model_version") or "")
        return {
            "span_count": span_count,
            "max_ts_end_ms": max_ts_end,
            "latest_state_id": latest_state_id,
            "latest_embedding_hash": latest_embedding_hash,
            "latest_model_version": latest_model_version,
        }

    def get_spans(
        self,
        *,
        session_id: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        app: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure()
        conn = self._conn
        if conn is None:
            return []
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if start_ms is not None:
            clauses.append("ts_end_ms >= ?")
            params.append(int(start_ms))
        if end_ms is not None:
            clauses.append("ts_start_ms <= ?")
            params.append(int(end_ms))
        if app:
            clauses.append("app = ?")
            params.append(app)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = "SELECT state_id, session_id, ts_start_ms, ts_end_ms, z_embedding, z_dim, z_dtype, app, window_title_hash, top_entities_json, provenance_json FROM state_span " + where + " ORDER BY ts_start_ms, state_id"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = conn.execute(sql, tuple(params)).fetchall()
        span_ids = [row[0] for row in rows]
        evidence_map = self._fetch_evidence("span", span_ids)
        spans: list[dict[str, Any]] = []
        for row in rows:
            top_entities: list[Any] = []
            try:
                top_entities = json.loads(row[9]) if row[9] else []
            except Exception:
                top_entities = []
            provenance: dict[str, Any] = {}
            try:
                provenance = json.loads(row[10]) if row[10] else {}
            except Exception:
                provenance = {}
            emb_blob = row[4] if row[4] is not None else b""
            span = {
                "state_id": row[0],
                "session_id": row[1],
                "ts_start_ms": int(row[2]),
                "ts_end_ms": int(row[3]),
                "z_embedding": {"dim": int(row[5]), "dtype": str(row[6]), "blob": b64encode(emb_blob)},
                "summary_features": {
                    "app": row[7] or "",
                    "window_title_hash": row[8] or "",
                    "top_entities": top_entities,
                },
                "evidence": evidence_map.get(str(row[0]), []),
                "provenance": provenance,
            }
            spans.append(span)
        return spans

    def get_edges_for_states(self, state_ids: Iterable[str]) -> list[dict[str, Any]]:
        self._ensure()
        conn = self._conn
        ids = [str(sid) for sid in state_ids if sid]
        if conn is None or not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT edge_id, from_state_id, to_state_id, delta_embedding, delta_dim, delta_dtype, pred_error, provenance_json FROM state_edge WHERE from_state_id IN ({placeholders}) OR to_state_id IN ({placeholders})",
            (*ids, *ids),
        ).fetchall()
        edge_ids = [row[0] for row in rows]
        evidence_map = self._fetch_evidence("edge", edge_ids)
        edges: list[dict[str, Any]] = []
        for row in rows:
            try:
                provenance = json.loads(row[7]) if row[7] else {}
            except Exception:
                provenance = {}
            emb_blob = row[3] if row[3] is not None else b""
            edge = {
                "edge_id": row[0],
                "from_state_id": row[1],
                "to_state_id": row[2],
                "delta_embedding": {"dim": int(row[4]), "dtype": str(row[5]), "blob": b64encode(emb_blob)},
                "pred_error": float(row[6]),
                "evidence": evidence_map.get(str(row[0]), []),
                "provenance": provenance,
            }
            edges.append(edge)
        return edges
