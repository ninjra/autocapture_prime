"""Mirror metadata.db -> metadata.live.db using SQLite online backup API.

This script runs on the SAME machine as the capture writer (Windows) and
periodically creates a consistent read snapshot of metadata.db. The snapshot
is written atomically (tmp + rename) so WSL readers never see a partial file.

sqlite3.backup() is safe to call while another process is writing under WAL
mode -- it acquires a shared lock, copies pages, and handles WAL correctly.
This is the standard SQLite mechanism for hot backup.

Usage (Windows, alongside capture):
    python tools/mirror_metadata_live.py [--data-dir D:\\autocapture] [--interval 30]

Usage (WSL, when capture is idle):
    python tools/mirror_metadata_live.py --data-dir /mnt/d/autocapture --once

The resulting metadata.live.db can be opened from WSL with immutable=1 mode
for zero-contention reads across the 9P filesystem bridge.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def mirror_once(
    src: Path,
    dst: Path,
    *,
    timeout: float = 10.0,
    pages_per_step: int = -1,
) -> dict:
    """Create a consistent snapshot of src at dst using sqlite3.backup().

    Uses atomic write (tmp file + os.replace) so readers never see a
    partial database.
    """
    if not src.exists():
        return {"ok": False, "error": "source_missing", "source": str(src)}

    tmp = dst.parent / (dst.name + ".tmp")
    src_conn: sqlite3.Connection | None = None
    dst_conn: sqlite3.Connection | None = None
    started = time.monotonic()
    src_size = 0
    try:
        src_size = src.stat().st_size
        src_conn = sqlite3.connect(
            f"file:{src}?mode=ro", uri=True, timeout=timeout
        )
        # Ensure we read a consistent snapshot even under active WAL writes.
        src_conn.execute("PRAGMA query_only = ON")

        dst_conn = sqlite3.connect(str(tmp), timeout=timeout)
        # Use journal_mode=DELETE for the snapshot so WSL readers don't need
        # to deal with WAL files across 9P.
        dst_conn.execute("PRAGMA journal_mode = DELETE")

        src_conn.backup(dst_conn, pages=pages_per_step)
        dst_conn.execute("PRAGMA integrity_check")
        dst_conn.commit()
    except Exception as exc:
        # Clean up partial tmp file on failure.
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return {
            "ok": False,
            "error": f"{type(exc).__name__}:{exc}",
            "source": str(src),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    finally:
        if dst_conn is not None:
            try:
                dst_conn.close()
            except Exception:
                pass
        if src_conn is not None:
            try:
                src_conn.close()
            except Exception:
                pass

    # Atomic rename so WSL never sees a half-written file.
    try:
        os.replace(str(tmp), str(dst))
    except Exception as exc:
        return {
            "ok": False,
            "error": f"rename_failed:{type(exc).__name__}:{exc}",
            "source": str(src),
            "tmp": str(tmp),
        }

    elapsed_ms = int((time.monotonic() - started) * 1000)
    dst_size = dst.stat().st_size if dst.exists() else 0
    return {
        "ok": True,
        "source": str(src),
        "destination": str(dst),
        "source_size_mb": round(src_size / (1024 * 1024), 1),
        "destination_size_mb": round(dst_size / (1024 * 1024), 1),
        "elapsed_ms": elapsed_ms,
        "ts_utc": _utc_iso(),
    }


def run_loop(
    data_dir: Path,
    *,
    interval_s: float = 30.0,
    once: bool = False,
) -> None:
    src = data_dir / "metadata.db"
    dst = data_dir / "metadata.live.db"

    print(f"[mirror] source={src}", file=sys.stderr)
    print(f"[mirror] destination={dst}", file=sys.stderr)
    print(f"[mirror] interval={interval_s}s once={once}", file=sys.stderr)

    consecutive_errors = 0
    while True:
        result = mirror_once(src, dst)
        ts = result.get("ts_utc") or _utc_iso()

        if result["ok"]:
            consecutive_errors = 0
            elapsed = result.get("elapsed_ms", 0)
            size = result.get("destination_size_mb", "?")
            print(
                f"[mirror] {ts} ok elapsed={elapsed}ms size={size}MB",
                file=sys.stderr,
            )
        else:
            consecutive_errors += 1
            err = result.get("error", "unknown")
            print(
                f"[mirror] {ts} FAIL ({consecutive_errors}) {err}",
                file=sys.stderr,
            )

        if once:
            if not result["ok"]:
                sys.exit(1)
            break

        # Back off on repeated errors but cap at 5 minutes.
        sleep = interval_s
        if consecutive_errors > 0:
            sleep = min(300.0, interval_s * (2 ** min(consecutive_errors, 5)))
        time.sleep(sleep)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mirror metadata.db -> metadata.live.db via SQLite backup API"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=os.environ.get("AUTOCAPTURE_DATA_DIR", ""),
        help="Data directory containing metadata.db",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.environ.get("AUTOCAPTURE_MIRROR_INTERVAL_S", "30")),
        help="Seconds between mirror cycles (default: 30)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single mirror and exit",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else None
    if data_dir is None or not data_dir.exists():
        # Auto-detect common locations.
        for candidate in [
            Path("D:/autocapture"),
            Path("/mnt/d/autocapture"),
        ]:
            if (candidate / "metadata.db").exists():
                data_dir = candidate
                break
    if data_dir is None or not (data_dir / "metadata.db").exists():
        print("FAIL: metadata.db not found. Set --data-dir or AUTOCAPTURE_DATA_DIR.", file=sys.stderr)
        sys.exit(2)

    run_loop(data_dir, interval_s=args.interval, once=args.once)


if __name__ == "__main__":
    main()
