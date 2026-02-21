"""Gate: lightweight performance regression checks."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
import time
import hashlib
from pathlib import Path
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
        frame_format="jpeg",
    )
    start = time.perf_counter()
    for frame in frames:
        writer.add_frame(frame)
    writer.finalize()
    elapsed = max(0.001, time.perf_counter() - start)
    total_mb = (frame_size * len(frames)) / (1024 * 1024)
    return total_mb / elapsed


def _measure_throughput(sample_count: int, frame_size: int, spool_dir: str) -> dict[str, float]:
    frame_bytes = b"x" * int(frame_size)
    frames = []
    for idx in range(sample_count):
        frames.append(
            Frame(
                ts_utc=f"2026-01-01T00:00:{idx:02d}Z",
                data=frame_bytes,
                width=64,
                height=64,
                ts_monotonic=float(idx),
            )
        )
    writer = SegmentWriter(
        spool_dir,
        segment_id="run1/segment/0",
        fps_target=30,
        bitrate_kbps=4000,
        container_type="avi_mjpeg",
        encoder="cpu",
        ffmpeg_path=None,
        frame_format="jpeg",
    )
    latencies_ms: list[float] = []
    start = time.perf_counter()
    for frame in frames:
        t0 = time.perf_counter()
        writer.add_frame(frame)
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)
    writer.finalize()
    elapsed = max(0.001, time.perf_counter() - start)
    artifacts_per_s = float(sample_count) / elapsed
    latencies_ms.sort()
    mid = len(latencies_ms) // 2
    median_ms = latencies_ms[mid] if latencies_ms else 0.0
    return {"artifacts_per_s": artifacts_per_s, "median_latency_ms": median_ms}


def _machine_fingerprint() -> str:
    payload = f"{platform.system()}|{platform.release()}|{platform.machine()}|{os.cpu_count()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _evaluate_regression(metrics: dict[str, float], baseline: dict[str, float], max_regression_pct: float) -> bool:
    if not baseline:
        return True
    base = float(baseline.get("artifacts_per_s", 0.0))
    if base <= 0:
        return True
    return float(metrics.get("artifacts_per_s", 0.0)) >= base * (1.0 - max_regression_pct)


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update-baseline", action="store_true", default=False)
    parser.add_argument("--backend", default="auto")
    args = parser.parse_args(argv)

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

    throughput_cfg = perf_cfg.get("throughput", {})
    max_regression_pct = float(throughput_cfg.get("max_regression_pct", 0.25))
    sample_count = int(throughput_cfg.get("sample_count", 50))
    min_artifacts_per_s = float(throughput_cfg.get("min_artifacts_per_s", 1000.0))

    def _measure_startup() -> float:
        # Run perf gate boot in an isolated temp data/config dir so:
        # - instance locks from other runs can't interfere
        # - encrypted stores don't trip over existing real user DB state
        # - retries don't leak locks/hosts
        with tempfile.TemporaryDirectory() as tmp_root:
            prev_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            prev_cfg = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp_root
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = str(Path(tmp_root) / "config")
            kernel = Kernel(paths, safe_mode=True)
            t0 = time.perf_counter()
            try:
                kernel.boot()
            finally:
                try:
                    kernel.shutdown()
                except Exception:
                    pass
                if prev_data is None:
                    os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_DATA_DIR"] = prev_data
                if prev_cfg is None:
                    os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_CONFIG_DIR"] = prev_cfg
            return (time.perf_counter() - t0) * 1000.0

    elapsed_ms = _measure_startup()
    print(f"startup_ms={elapsed_ms:.1f} max_ms={max_startup_ms}")
    retries = 0
    while elapsed_ms > max_startup_ms and retries < 2:
        retry_ms = _measure_startup()
        retries += 1
        suffix = "retry" if retries == 1 else f"retry{retries}"
        print(f"startup_ms_{suffix}={retry_ms:.1f} max_ms={max_startup_ms}")
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

    artifacts_dir = Path("artifacts") / "perf"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = artifacts_dir / "perf_baseline.json"
    metrics_samples: list[dict[str, float | str | int]] = []
    with tempfile.TemporaryDirectory() as tmp:
        metrics = _measure_throughput(sample_count, 200_000, tmp)
    metrics_payload = {
        "artifacts_per_s": metrics["artifacts_per_s"],
        "median_latency_ms": metrics["median_latency_ms"],
        "backend": str(args.backend),
        "sample_count": int(sample_count),
        "fingerprint": _machine_fingerprint(),
    }
    metrics_samples.append(metrics_payload)
    baseline = {}
    if baseline_path.exists():
        try:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        except Exception:
            baseline = {}
    gate_payload = {
        "baseline": baseline,
        "metrics": metrics_payload,
        "metrics_samples": metrics_samples,
        "max_regression_pct": max_regression_pct,
        "min_artifacts_per_s": min_artifacts_per_s,
    }
    (artifacts_dir / "gate_perf.json").write_text(json.dumps(gate_payload, indent=2, sort_keys=True), encoding="utf-8")
    if args.update_baseline or not baseline:
        baseline_path.write_text(json.dumps(metrics_payload, indent=2, sort_keys=True), encoding="utf-8")
        print("OK: perf gate (baseline updated)")
        return 0
    if not _evaluate_regression(metrics_payload, baseline, max_regression_pct):
        with tempfile.TemporaryDirectory() as tmp:
            retry_metrics = _measure_throughput(sample_count, 200_000, tmp)
        retry_payload = {
            "artifacts_per_s": retry_metrics["artifacts_per_s"],
            "median_latency_ms": retry_metrics["median_latency_ms"],
            "backend": str(args.backend),
            "sample_count": int(sample_count),
            "fingerprint": _machine_fingerprint(),
        }
        metrics_samples.append(retry_payload)
        metrics_payload = max(
            metrics_samples,
            key=lambda sample: float(sample.get("artifacts_per_s", 0.0)),
        )
        gate_payload["metrics"] = metrics_payload
        gate_payload["metrics_samples"] = metrics_samples
        (artifacts_dir / "gate_perf.json").write_text(
            json.dumps(gate_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        if not _evaluate_regression(metrics_payload, baseline, max_regression_pct):
            if float(metrics_payload.get("artifacts_per_s", 0.0)) >= min_artifacts_per_s:
                gate_payload["regression"] = True
                (artifacts_dir / "gate_perf.json").write_text(
                    json.dumps(gate_payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                print("WARN: throughput regression (above minimum floor)")
                return 0
            print("FAIL: throughput regression")
            return 1

    print("OK: perf gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
