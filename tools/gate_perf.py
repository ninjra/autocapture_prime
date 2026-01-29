"""Gate: lightweight performance regression checks."""

from __future__ import annotations

import os
import time
import tempfile
import sys
try:
    import resource  # type: ignore
except Exception:  # pragma: no cover - not available on Windows
    resource = None  # type: ignore[assignment]

from autocapture_nx.kernel.config import load_config
from autocapture_nx.kernel.loader import Kernel, default_config_paths
from autocapture_nx.capture.pipeline import SegmentWriter
from autocapture_nx.windows.win_capture import Frame
from autocapture_nx.kernel.query import _evidence_candidates


def _rss_mb() -> float:
    if resource is None:
        return 0.0
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return float(usage) / (1024 * 1024)
    return float(usage) / 1024


def _measure_ingestion_mb_s(spool_dir: str) -> float:
    frame_size = 200_000
    frame_bytes = b"x" * frame_size
    frames = []
    for idx in range(20):
        frames.append(Frame(ts_utc=f"2026-01-01T00:00:{idx:02d}Z", data=frame_bytes, width=64, height=64, ts_monotonic=float(idx)))
    writer = SegmentWriter(
        spool_dir,
        segment_id="run1/segment/0",
        fps_target=30,
        bitrate_kbps=4000,
        container_type="avi_mjpeg",
        encoder="cpu",
        ffmpeg_path=None,
    )
    start = time.perf_counter()
    for frame in frames:
        writer.add_frame(frame)
    writer.finalize()
    elapsed = max(0.001, time.perf_counter() - start)
    total_mb = (frame_size * len(frames)) / (1024 * 1024)
    return total_mb / elapsed


def _measure_query_latency_ms() -> float:
    records = {}
    for idx in range(2000):
        ts = f"2026-01-01T00:{idx // 60:02d}:{idx % 60:02d}Z"
        record_id = f"run1/evidence.capture.frame/{idx}"
        records[record_id] = {"record_type": "evidence.capture.frame", "ts_utc": ts}

    class _Store:
        def keys(self):
            return list(records.keys())

        def get(self, key, default=None):
            return records.get(key, default)

    store = _Store()
    t0 = time.perf_counter()
    _evidence_candidates(store, None, limit=50)
    return (time.perf_counter() - t0) * 1000.0


def main() -> int:
    os.environ.setdefault("AUTOCAPTURE_SAFE_MODE_MINIMAL", "1")
    paths = default_config_paths()
    config = load_config(paths, safe_mode=True)
    perf_cfg = config.get("performance", {})
    startup_target = int(perf_cfg.get("startup_ms", 1000))
    max_startup_ms = max(startup_target * 5, 3000)
    query_target = int(perf_cfg.get("query_latency_ms", 2000))
    max_query_ms = max(query_target * 5, 3000)
    ingestion_target = int(perf_cfg.get("ingestion_mb_s", 50))
    min_ingest_mb_s = max(1.0, ingestion_target / 5.0)
    memory_ceiling = int(perf_cfg.get("memory_ceiling_mb", 512))

    def _measure_startup() -> float:
        t0 = time.perf_counter()
        Kernel(paths, safe_mode=True).boot()
        return (time.perf_counter() - t0) * 1000.0

    elapsed_ms = _measure_startup()
    print(f"startup_ms={elapsed_ms:.1f} max_ms={max_startup_ms}")
    if elapsed_ms > max_startup_ms:
        retry_ms = _measure_startup()
        print(f"startup_ms_retry={retry_ms:.1f} max_ms={max_startup_ms}")
        elapsed_ms = min(elapsed_ms, retry_ms)
    if elapsed_ms > max_startup_ms:
        print("FAIL: startup time regression")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        ingest_mb_s = _measure_ingestion_mb_s(tmp)
    print(f"ingestion_mb_s={ingest_mb_s:.1f} min_mb_s={min_ingest_mb_s}")
    if ingest_mb_s < min_ingest_mb_s:
        print("FAIL: ingestion throughput regression")
        return 1

    query_ms = _measure_query_latency_ms()
    print(f"query_ms={query_ms:.1f} max_ms={max_query_ms}")
    if query_ms > max_query_ms:
        print("FAIL: query latency regression")
        return 1

    rss_mb = _rss_mb()
    print(f"rss_mb={rss_mb:.1f} max_mb={memory_ceiling}")
    if rss_mb > memory_ceiling:
        print("FAIL: memory ceiling exceeded")
        return 1

    print("OK: perf gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
