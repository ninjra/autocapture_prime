"""Stage-1 handoff ingestion (ultralight, deterministic, restartable)."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from autocapture_nx.kernel.atomic_write import atomic_write_json
from autocapture_nx.kernel.hashing import sha256_file
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.kernel.instance_lock import acquire_instance_lock
from autocapture_nx.ingest.stage2_projection_docs import project_stage2_docs_for_frame
from autocapture_nx.ingest.uia_obs_docs import _ensure_frame_uia_docs
from autocapture_nx.storage.stage1_derived_store import Stage1DerivedSqliteStore
from autocapture_nx.storage.stage1_derived_store import Stage1OverlayStore
from autocapture_nx.storage.stage1_derived_store import default_stage1_derived_db_path
from autocapture.storage.stage1 import mark_stage1_and_retention

_REAP_MARKER = "reap_eligible.json"
_REAP_SCHEMA = "autocapture.handoff.reap_eligible.v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return [str(row[1]) for row in cur.fetchall()]


def _choose_source_table(conn: sqlite3.Connection) -> str:
    if _table_exists(conn, "metadata"):
        return "metadata"
    if _table_exists(conn, "records"):
        return "records"
    raise RuntimeError("handoff_metadata_table_missing")


def _ensure_dest_metadata_table(conn: sqlite3.Connection) -> str:
    if _table_exists(conn, "metadata"):
        return "metadata"
    if _table_exists(conn, "records"):
        return "records"
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            id TEXT PRIMARY KEY,
            record_type TEXT,
            ts_utc TEXT,
            payload TEXT,
            run_id TEXT,
            nonce_b64 TEXT,
            ciphertext_b64 TEXT,
            key_id TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_metadata_record_type ON metadata(record_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_metadata_ts_utc ON metadata(ts_utc)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_metadata_run_id ON metadata(run_id)")
    conn.commit()
    return "metadata"


def _decode_payload_text(payload_text: str | None) -> dict[str, Any] | None:
    if not payload_text:
        return None
    try:
        value = json.loads(payload_text)
    except Exception:
        return None
    if isinstance(value, dict):
        return value
    return None


def _extract_media_refs(value: Any) -> set[str]:
    refs: set[str] = set()

    def visit(node: Any, key_hint: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                visit(v, str(k))
            return
        if isinstance(node, list):
            for item in node:
                visit(item, key_hint)
            return
        if not isinstance(node, str):
            return
        key_l = key_hint.lower()
        if key_l not in {"blob_path", "media_path", "media_relpath"} and not key_l.endswith("blob_path"):
            return
        text = node.replace("\\", "/").strip()
        if not text:
            return
        marker = "media/"
        if marker in text:
            text = text[text.index(marker) + len(marker) :]
        text = text.lstrip("/")
        if text:
            refs.add(text)

    visit(value)
    return refs


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except Exception:
        return
    try:
        try:
            os.fsync(fd)
        except Exception:
            return
    finally:
        try:
            os.close(fd)
        except Exception:
            pass


def _copy_file_atomic(src: Path, dst: Path) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dst.name}.", suffix=".tmp", dir=str(dst.parent))
    size = 0
    try:
        with os.fdopen(fd, "wb") as out_fh:
            with src.open("rb") as in_fh:
                while True:
                    chunk = in_fh.read(1024 * 1024)
                    if not chunk:
                        break
                    out_fh.write(chunk)
                    size += len(chunk)
            out_fh.flush()
            try:
                os.fsync(out_fh.fileno())
            except Exception:
                pass
        os.replace(tmp_name, str(dst))
        _fsync_dir(dst.parent)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except Exception:
            pass
    return size


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _marker_requires_retry(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if str(payload.get("schema") or "") != _REAP_SCHEMA:
        return False
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    missing_retention = _safe_int(counts.get("stage1_missing_retention_marker_count", 0)) > 0
    missing_uia = _safe_int(counts.get("stage1_uia_frames_missing_count", 0)) > 0
    return bool(missing_retention or missing_uia)


@dataclass(frozen=True)
class IngestResult:
    handoff_root: str
    dest_data_root: str
    ingest_run_id: str
    started_utc: str
    ended_utc: str
    metadata_rows_copied: int
    media_files_linked: int
    media_files_copied: int
    bytes_ingested: int
    stage1_complete_records: int
    stage1_retention_marked_records: int
    stage1_missing_retention_marker_count: int
    stage1_uia_docs_inserted: int
    stage1_uia_frames_missing_count: int
    stage2_projection_generated_docs: int
    stage2_projection_inserted_docs: int
    stage2_projection_errors: int
    ack_path: str
    journal_record_id: str
    errors: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DrainResult:
    spool_root: str
    dest_data_root: str
    processed: int
    skipped_marked: int
    errors: list[dict[str, Any]]
    results: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class _SqliteMetadataAdapter:
    def __init__(self, conn: sqlite3.Connection, table: str, columns: set[str]) -> None:
        self._conn = conn
        self._table = str(table)
        self._columns = {str(col) for col in columns}
        self._id_col = "id" if "id" in self._columns else ("record_id" if "record_id" in self._columns else "")
        if not self._id_col:
            raise RuntimeError("destination metadata table missing id/record_id column")
        self._payload_col = "payload" if "payload" in self._columns else ("payload_json" if "payload_json" in self._columns else "")
        self._record_type_col = "record_type" if "record_type" in self._columns else ""
        self._ts_col = "ts_utc" if "ts_utc" in self._columns else ""
        self._run_id_col = "run_id" if "run_id" in self._columns else ""

    def _select_sql(self) -> str:
        cols = [self._id_col]
        if self._payload_col:
            cols.append(self._payload_col)
        if self._record_type_col:
            cols.append(self._record_type_col)
        if self._ts_col:
            cols.append(self._ts_col)
        if self._run_id_col:
            cols.append(self._run_id_col)
        return f"SELECT {','.join(cols)} FROM {self._table} WHERE {self._id_col} = ?"

    def get(self, record_id: str, default: Any = None) -> Any:
        row = self._conn.execute(self._select_sql(), (str(record_id),)).fetchone()
        if row is None:
            return default
        col_idx = 1
        if self._payload_col:
            payload_val = row[col_idx]
            col_idx += 1
            if isinstance(payload_val, str) and payload_val.strip():
                try:
                    parsed = json.loads(payload_val)
                except Exception:
                    parsed = None
                if isinstance(parsed, dict):
                    return parsed
        out: dict[str, Any] = {}
        if self._record_type_col:
            out["record_type"] = str(row[col_idx] or "")
            col_idx += 1
        if self._ts_col:
            out["ts_utc"] = str(row[col_idx] or "")
            col_idx += 1
        if self._run_id_col:
            out["run_id"] = str(row[col_idx] or "")
        return out if out else default

    def put_new(self, record_id: str, value: dict[str, Any]) -> None:
        cols: list[str] = [self._id_col]
        vals: list[Any] = [str(record_id)]
        if self._record_type_col:
            cols.append(self._record_type_col)
            vals.append(str(value.get("record_type") or ""))
        if self._ts_col:
            cols.append(self._ts_col)
            vals.append(str(value.get("ts_utc") or value.get("ts_start_utc") or value.get("ts_end_utc") or ""))
        if self._payload_col:
            cols.append(self._payload_col)
            vals.append(json.dumps(value, sort_keys=True))
        if self._run_id_col:
            cols.append(self._run_id_col)
            vals.append(str(value.get("run_id") or ""))
        sql = f"INSERT INTO {self._table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
        try:
            self._conn.execute(sql, tuple(vals))
        except sqlite3.IntegrityError as exc:
            raise FileExistsError(str(record_id)) from exc

    def put(self, record_id: str, value: dict[str, Any]) -> None:
        cols: list[str] = [self._id_col]
        vals: list[Any] = [str(record_id)]
        if self._record_type_col:
            cols.append(self._record_type_col)
            vals.append(str(value.get("record_type") or ""))
        if self._ts_col:
            cols.append(self._ts_col)
            vals.append(str(value.get("ts_utc") or value.get("ts_start_utc") or value.get("ts_end_utc") or ""))
        if self._payload_col:
            cols.append(self._payload_col)
            vals.append(json.dumps(value, sort_keys=True))
        if self._run_id_col:
            cols.append(self._run_id_col)
            vals.append(str(value.get("run_id") or ""))
        sql = f"INSERT OR REPLACE INTO {self._table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
        self._conn.execute(sql, tuple(vals))


class HandoffIngestor:
    def __init__(self, dest_data_root: Path, *, mode: str = "copy", strict: bool = True) -> None:
        if str(mode) not in {"copy", "hardlink"}:
            raise ValueError("mode must be copy or hardlink")
        self._dest_data_root = Path(dest_data_root).expanduser().resolve()
        self._mode = str(mode)
        self._strict = bool(strict)

    def ingest_handoff_dir(self, handoff_root: Path) -> IngestResult:
        handoff = Path(handoff_root).expanduser().resolve()
        metadata_path = handoff / "metadata.db"
        if not metadata_path.exists():
            raise FileNotFoundError(f"handoff metadata.db missing: {metadata_path}")

        started_utc = _utc_now()
        ingest_run_id = f"ingest_{started_utc.replace(':', '').replace('-', '').replace('.', '')}"
        source_media_root = handoff / "media"
        dest_media_root = self._dest_data_root / "media"
        dest_db_path = self._dest_data_root / "metadata.db"
        self._dest_data_root.mkdir(parents=True, exist_ok=True)
        dest_media_root.mkdir(parents=True, exist_ok=True)

        metadata_rows_copied = 0
        media_files_linked = 0
        media_files_copied = 0
        bytes_ingested = 0
        stage1_complete_records = 0
        stage1_retention_marked_records = 0
        stage1_missing_retention_marker_count = 0
        stage1_uia_docs_inserted = 0
        stage1_uia_frames_missing_count = 0
        stage2_projection_generated_docs = 0
        stage2_projection_inserted_docs = 0
        stage2_projection_errors = 0
        journal_record_id = ""
        errors: list[str] = []

        lock = acquire_instance_lock(self._dest_data_root)
        try:
            src_conn = sqlite3.connect(f"file:{metadata_path}?mode=ro", uri=True)
            src_conn.row_factory = sqlite3.Row
            dst_conn = sqlite3.connect(str(dest_db_path))
            dst_conn.row_factory = sqlite3.Row
            try:
                source_table = _choose_source_table(src_conn)
                source_cols = set(_table_columns(src_conn, source_table))
                dest_table = _ensure_dest_metadata_table(dst_conn)
                dest_cols = set(_table_columns(dst_conn, dest_table))

                rows: list[dict[str, Any]] = []
                stage1_candidates: list[tuple[str, dict[str, Any]]] = []
                refs: set[str] = set()
                src_cur = src_conn.execute(f"SELECT * FROM {source_table}")
                for row in src_cur:
                    payload_text = None
                    if "payload" in source_cols:
                        payload_text = row["payload"]
                    elif "payload_json" in source_cols:
                        payload_text = row["payload_json"]
                    payload = _decode_payload_text(payload_text if isinstance(payload_text, str) else None)
                    if payload is not None:
                        refs.update(_extract_media_refs(payload))
                        source_record_id = str(row["id"] if "id" in source_cols else row["record_id"])
                        stage1_candidates.append((source_record_id, dict(payload)))
                    row_payload: dict[str, Any] = {}
                    row_payload["id"] = row["id"] if "id" in source_cols else row["record_id"]
                    row_payload["record_type"] = row["record_type"] if "record_type" in source_cols else (
                        str(payload.get("record_type")) if isinstance(payload, dict) and payload.get("record_type") else None
                    )
                    row_payload["ts_utc"] = row["ts_utc"] if "ts_utc" in source_cols else (
                        str(payload.get("ts_utc")) if isinstance(payload, dict) and payload.get("ts_utc") else None
                    )
                    row_payload["run_id"] = row["run_id"] if "run_id" in source_cols else (
                        str(payload.get("run_id")) if isinstance(payload, dict) and payload.get("run_id") else None
                    )
                    row_payload["payload"] = payload_text if isinstance(payload_text, str) else None
                    for key in ("nonce_b64", "ciphertext_b64", "key_id"):
                        if key in source_cols:
                            row_payload[key] = row[key]
                    rows.append(row_payload)

                missing_refs: list[str] = []
                for ref in sorted(refs):
                    src_file = source_media_root / ref
                    dst_file = dest_media_root / ref
                    if src_file.exists() or dst_file.exists():
                        continue
                    missing_refs.append(ref)
                if missing_refs and self._strict:
                    raise FileNotFoundError(f"handoff missing media refs: {missing_refs[:10]}")

                insert_cols = [col for col in ("id", "record_type", "ts_utc", "payload", "run_id", "nonce_b64", "ciphertext_b64", "key_id") if col in dest_cols]
                placeholders = ",".join("?" for _ in insert_cols)
                sql = f"INSERT OR IGNORE INTO {dest_table} ({','.join(insert_cols)}) VALUES ({placeholders})"
                dst_conn.execute("BEGIN")
                for row_payload in rows:
                    values = [row_payload.get(col) for col in insert_cols]
                    cur = dst_conn.execute(sql, values)
                    metadata_rows_copied += _safe_int(cur.rowcount)
                dst_conn.commit()

                if source_media_root.exists():
                    for src_file in sorted(source_media_root.rglob("*")):
                        if not src_file.is_file():
                            continue
                        rel = src_file.relative_to(source_media_root)
                        dst_file = dest_media_root / rel
                        if dst_file.exists():
                            continue
                        dst_file.parent.mkdir(parents=True, exist_ok=True)
                        if self._mode == "hardlink":
                            try:
                                os.link(src_file, dst_file)
                                media_files_linked += 1
                                bytes_ingested += _safe_int(src_file.stat().st_size)
                                continue
                            except OSError:
                                pass
                        copied = _copy_file_atomic(src_file, dst_file)
                        if _safe_int(dst_file.stat().st_size) != _safe_int(src_file.stat().st_size):
                            raise RuntimeError(f"copied file size mismatch: {src_file} -> {dst_file}")
                        media_files_copied += 1
                        bytes_ingested += copied
                elif self._strict and refs:
                    raise FileNotFoundError(f"handoff media directory missing: {source_media_root}")

                stage1_read_store = _SqliteMetadataAdapter(dst_conn, dest_table, dest_cols)
                stage1_store: Any | None = None
                try:
                    derived_path = default_stage1_derived_db_path(self._dest_data_root)
                    derived_store = Stage1DerivedSqliteStore(derived_path)
                    stage1_store = Stage1OverlayStore(metadata_read=stage1_read_store, derived_write=derived_store)
                except Exception as exc:
                    errors.append(f"stage1_derived_store_error:{type(exc).__name__}:{exc}")
                for source_record_id, source_payload in stage1_candidates:
                    if str(source_payload.get("record_type") or "") != "evidence.capture.frame":
                        continue
                    if stage1_store is None:
                        stage1_missing_retention_marker_count += 1
                        continue
                    uia_status = _ensure_frame_uia_docs(
                        stage1_store,
                        source_record_id=source_record_id,
                        record=source_payload,
                        dataroot=str(self._dest_data_root),
                        snapshot_metadata=stage1_read_store,
                    )
                    stage1_uia_docs_inserted += _safe_int(uia_status.get("inserted", 0))
                    if bool(uia_status.get("required", False)) and not bool(uia_status.get("ok", False)):
                        stage1_uia_frames_missing_count += 1
                        stage1_missing_retention_marker_count += 1
                        continue
                    try:
                        projection = project_stage2_docs_for_frame(
                            stage1_read_store,
                            source_record_id=source_record_id,
                            frame_record=source_payload,
                            read_store=stage1_store,
                            dry_run=False,
                        )
                        stage2_projection_generated_docs += _safe_int(projection.get("generated_docs", 0))
                        stage2_projection_inserted_docs += _safe_int(projection.get("inserted_docs", 0))
                        stage2_projection_errors += _safe_int(projection.get("errors", 0))
                    except Exception:
                        stage2_projection_errors += 1
                    try:
                        result = mark_stage1_and_retention(
                            stage1_store,
                            source_record_id,
                            source_payload,
                            reason="handoff_ingest",
                        )
                    except Exception:
                        continue
                    if bool(result.get("stage1_complete", False)):
                        stage1_complete_records += 1
                    if bool(result.get("retention_record_id")):
                        stage1_retention_marked_records += 1
                    if bool(result.get("retention_missing", False)):
                        stage1_missing_retention_marker_count += 1

                handoff_hash = sha256_file(metadata_path)
                handoff_key = encode_record_id_component(f"{handoff.name}:{handoff_hash}")
                run_part = str((rows[0].get("run_id") if rows else "") or "handoff")
                journal_record_id = f"{run_part}/system.ingest.handoff.completed/{handoff_key}"
                payload = {
                    "schema_version": 1,
                    "record_type": "system.ingest.handoff.completed",
                    "run_id": run_part,
                    "ts_utc": _utc_now(),
                    "handoff_root": str(handoff),
                    "dest_data_root": str(self._dest_data_root),
                    "handoff_hash": handoff_hash,
                    "counts": {
                        "metadata_rows_copied": int(metadata_rows_copied),
                        "media_files_linked": int(media_files_linked),
                        "media_files_copied": int(media_files_copied),
                        "bytes_ingested": int(bytes_ingested),
                        "stage1_complete_records": int(stage1_complete_records),
                        "stage1_retention_marked_records": int(stage1_retention_marked_records),
                        "stage1_missing_retention_marker_count": int(stage1_missing_retention_marker_count),
                        "stage1_uia_docs_inserted": int(stage1_uia_docs_inserted),
                        "stage1_uia_frames_missing_count": int(stage1_uia_frames_missing_count),
                        "stage2_projection_generated_docs": int(stage2_projection_generated_docs),
                        "stage2_projection_inserted_docs": int(stage2_projection_inserted_docs),
                        "stage2_projection_errors": int(stage2_projection_errors),
                    },
                    "errors": [],
                }
                journal_cols = [col for col in ("id", "record_type", "ts_utc", "payload", "run_id") if col in dest_cols]
                journal_values: dict[str, Any] = {
                    "id": journal_record_id,
                    "record_type": payload["record_type"],
                    "ts_utc": payload["ts_utc"],
                    "payload": json.dumps(payload, sort_keys=True),
                    "run_id": payload["run_id"],
                }
                j_sql = f"INSERT OR IGNORE INTO {dest_table} ({','.join(journal_cols)}) VALUES ({','.join('?' for _ in journal_cols)})"
                dst_conn.execute(j_sql, [journal_values.get(col) for col in journal_cols])
                dst_conn.commit()
            finally:
                try:
                    src_conn.close()
                except Exception:
                    pass
                try:
                    dst_conn.close()
                except Exception:
                    pass
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            lock.close()

        ended_utc = _utc_now()
        ack_path = handoff / _REAP_MARKER
        marker = {
            "schema": _REAP_SCHEMA,
            "handoff_root": str(handoff),
            "dest_data_root": str(self._dest_data_root),
            "ingested_at_utc": ended_utc,
            "ingest_run_id": ingest_run_id,
            "counts": {
                "metadata_rows_copied": int(metadata_rows_copied),
                "media_files_linked": int(media_files_linked),
                "media_files_copied": int(media_files_copied),
                "bytes_ingested": int(bytes_ingested),
                "stage1_complete_records": int(stage1_complete_records),
                "stage1_retention_marked_records": int(stage1_retention_marked_records),
                "stage1_missing_retention_marker_count": int(stage1_missing_retention_marker_count),
                "stage1_uia_docs_inserted": int(stage1_uia_docs_inserted),
                "stage1_uia_frames_missing_count": int(stage1_uia_frames_missing_count),
                "stage2_projection_generated_docs": int(stage2_projection_generated_docs),
                "stage2_projection_inserted_docs": int(stage2_projection_inserted_docs),
                "stage2_projection_errors": int(stage2_projection_errors),
            },
            "integrity": {
                "dest_metadata_db_sha256": sha256_file(self._dest_data_root / "metadata.db"),
                "notes": "",
            },
        }
        atomic_write_json(ack_path, marker, sort_keys=True, indent=2)
        return IngestResult(
            handoff_root=str(handoff),
            dest_data_root=str(self._dest_data_root),
            ingest_run_id=ingest_run_id,
            started_utc=started_utc,
            ended_utc=ended_utc,
            metadata_rows_copied=int(metadata_rows_copied),
            media_files_linked=int(media_files_linked),
            media_files_copied=int(media_files_copied),
            bytes_ingested=int(bytes_ingested),
            stage1_complete_records=int(stage1_complete_records),
            stage1_retention_marked_records=int(stage1_retention_marked_records),
            stage1_missing_retention_marker_count=int(stage1_missing_retention_marker_count),
            stage1_uia_docs_inserted=int(stage1_uia_docs_inserted),
            stage1_uia_frames_missing_count=int(stage1_uia_frames_missing_count),
            stage2_projection_generated_docs=int(stage2_projection_generated_docs),
            stage2_projection_inserted_docs=int(stage2_projection_inserted_docs),
            stage2_projection_errors=int(stage2_projection_errors),
            ack_path=str(ack_path),
            journal_record_id=journal_record_id,
            errors=list(errors),
        )

    def drain_spool(self, spool_root: Path, *, include_marked: bool = False, fail_fast: bool = False) -> DrainResult:
        root = Path(spool_root).expanduser().resolve()
        processed = 0
        skipped_marked = 0
        errors: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        candidates: Iterable[Path] = []
        if root.exists():
            candidates = sorted([p for p in root.iterdir() if p.is_dir()])
        for handoff in candidates:
            if not (handoff / "metadata.db").exists():
                continue
            marker_path = handoff / _REAP_MARKER
            if marker_path.exists() and not include_marked:
                try:
                    payload = json.loads(marker_path.read_text(encoding="utf-8"))
                except Exception:
                    payload = {}
                if isinstance(payload, dict) and str(payload.get("schema") or "") == _REAP_SCHEMA and not _marker_requires_retry(payload):
                    skipped_marked += 1
                    continue
            try:
                result = self.ingest_handoff_dir(handoff)
                processed += 1
                results.append(result.as_dict())
            except Exception as exc:
                row = {"handoff_root": str(handoff), "error": f"{type(exc).__name__}: {exc}"}
                errors.append(row)
                if fail_fast:
                    break
        return DrainResult(
            spool_root=str(root),
            dest_data_root=str(self._dest_data_root),
            processed=int(processed),
            skipped_marked=int(skipped_marked),
            errors=errors,
            results=results,
        )


def auto_drain_handoff_spool(
    config: dict[str, Any],
    *,
    include_marked: bool = False,
    fail_fast: bool = False,
) -> dict[str, Any]:
    """Best-effort Stage1 handoff drain from runtime config.

    This is intentionally fail-open for runtime stability: any drain failure is
    reported in the returned payload and callers should continue processing.
    """

    if not isinstance(config, dict):
        return {"ok": True, "enabled": False, "reason": "config_missing"}
    storage_cfg = config.get("storage", {})
    if not isinstance(storage_cfg, dict):
        return {"ok": True, "enabled": False, "reason": "storage_config_missing"}
    data_dir_raw = str(storage_cfg.get("data_dir") or "").strip()
    spool_root_raw = str(storage_cfg.get("spool_dir") or "").strip()
    if not data_dir_raw or not spool_root_raw:
        return {"ok": True, "enabled": False, "reason": "missing_data_or_spool_dir"}

    processing_cfg = config.get("processing", {})
    idle_cfg = processing_cfg.get("idle", {}) if isinstance(processing_cfg, dict) else {}
    handoff_cfg = idle_cfg.get("handoff_ingest", {}) if isinstance(idle_cfg, dict) else {}
    if not isinstance(handoff_cfg, dict):
        handoff_cfg = {}
    enabled = bool(handoff_cfg.get("enabled", True))
    if not enabled:
        return {"ok": True, "enabled": False, "reason": "handoff_ingest_disabled"}

    mode = str(handoff_cfg.get("mode", "hardlink") or "hardlink").strip().lower()
    if mode not in {"copy", "hardlink"}:
        mode = "hardlink"
    strict = bool(handoff_cfg.get("strict", True))
    include_marked_flag = bool(handoff_cfg.get("include_marked", include_marked))
    fail_fast_flag = bool(handoff_cfg.get("fail_fast", fail_fast))

    try:
        ingestor = HandoffIngestor(Path(data_dir_raw), mode=mode, strict=strict)
        drained = ingestor.drain_spool(
            Path(spool_root_raw),
            include_marked=include_marked_flag,
            fail_fast=fail_fast_flag,
        )
    except Exception as exc:  # pragma: no cover - defensive fail-open
        return {
            "ok": False,
            "enabled": True,
            "spool_root": str(spool_root_raw),
            "data_dir": str(data_dir_raw),
            "error": f"{type(exc).__name__}: {exc}",
        }

    results = drained.results if isinstance(drained.results, list) else []
    stage1_complete_records = 0
    stage1_retention_marked_records = 0
    stage1_missing_retention_marker_count = 0
    stage1_uia_docs_inserted = 0
    stage1_uia_frames_missing_count = 0
    stage2_projection_generated_docs = 0
    stage2_projection_inserted_docs = 0
    stage2_projection_errors = 0
    for row in results:
        if not isinstance(row, dict):
            continue
        stage1_complete_records += _safe_int(row.get("stage1_complete_records", 0))
        stage1_retention_marked_records += _safe_int(row.get("stage1_retention_marked_records", 0))
        stage1_missing_retention_marker_count += _safe_int(row.get("stage1_missing_retention_marker_count", 0))
        stage1_uia_docs_inserted += _safe_int(row.get("stage1_uia_docs_inserted", 0))
        stage1_uia_frames_missing_count += _safe_int(row.get("stage1_uia_frames_missing_count", 0))
        stage2_projection_generated_docs += _safe_int(row.get("stage2_projection_generated_docs", 0))
        stage2_projection_inserted_docs += _safe_int(row.get("stage2_projection_inserted_docs", 0))
        stage2_projection_errors += _safe_int(row.get("stage2_projection_errors", 0))
    return {
        "ok": len(drained.errors) == 0,
        "enabled": True,
        "spool_root": str(drained.spool_root),
        "data_dir": str(drained.dest_data_root),
        "processed": int(drained.processed),
        "skipped_marked": int(drained.skipped_marked),
        "errors": int(len(drained.errors)),
        "stage1_complete_records": int(stage1_complete_records),
        "stage1_retention_marked_records": int(stage1_retention_marked_records),
        "stage1_missing_retention_marker_count": int(stage1_missing_retention_marker_count),
        "stage1_uia_docs_inserted": int(stage1_uia_docs_inserted),
        "stage1_uia_frames_missing_count": int(stage1_uia_frames_missing_count),
        "stage2_projection_generated_docs": int(stage2_projection_generated_docs),
        "stage2_projection_inserted_docs": int(stage2_projection_inserted_docs),
        "stage2_projection_errors": int(stage2_projection_errors),
    }
