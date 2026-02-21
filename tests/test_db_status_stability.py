from __future__ import annotations

import threading
import time

from autocapture_nx.kernel.db_status import db_status_snapshot, metadata_db_stability_snapshot


def test_metadata_db_stability_snapshot_static_file(tmp_path) -> None:
    meta = tmp_path / "metadata.db"
    meta.write_bytes(b"sqlite")
    cfg = {"storage": {"metadata_path": str(meta)}}
    out = metadata_db_stability_snapshot(cfg, sample_count=3, poll_interval_ms=5)
    assert bool(out.get("exists", False))
    assert bool(out.get("ok", False))
    assert out.get("stable") is True
    assert int(out.get("churn_events", 99)) == 0


def test_metadata_db_stability_snapshot_detects_churn(tmp_path) -> None:
    meta = tmp_path / "metadata.db"
    meta.write_bytes(b"seed")
    stop = threading.Event()

    def _churn() -> None:
        i = 0
        while not stop.is_set():
            i += 1
            meta.write_bytes(f"seed-{i}".encode("utf-8"))
            time.sleep(0.003)

    t = threading.Thread(target=_churn, daemon=True)
    t.start()
    try:
        out = metadata_db_stability_snapshot(
            {"storage": {"metadata_path": str(meta)}},
            sample_count=6,
            poll_interval_ms=10,
        )
    finally:
        stop.set()
        t.join(timeout=0.5)
    assert bool(out.get("exists", False))
    assert out.get("stable") is False
    assert bool(out.get("ok", True)) is False
    assert int(out.get("churn_events", 0) or 0) >= 1


def test_db_status_snapshot_lightweight_mode_skips_hash_and_pragmas(tmp_path) -> None:
    meta = tmp_path / "metadata.db"
    meta.write_bytes(b"sqlite")
    cfg = {"storage": {"metadata_path": str(meta)}}
    snap = db_status_snapshot(
        cfg,
        include_hash=False,
        include_pragmas=False,
        include_stability=True,
        stability_samples=2,
        stability_poll_interval_ms=5,
    )
    rows = snap.get("dbs", [])
    metadata_rows = [row for row in rows if isinstance(row, dict) and row.get("name") == "metadata"]
    assert metadata_rows, "metadata row missing"
    row = metadata_rows[0]
    assert row.get("exists") is True
    assert row.get("sha256") is None
    assert row.get("sqlite_user_version") is None
    assert row.get("sqlite_schema_version") is None
    assert row.get("stable") is True
