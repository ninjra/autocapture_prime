"""Run fixture pipeline step-by-step with timeouts and detailed logging."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from autocapture_nx.kernel.loader import Kernel, default_config_paths
from autocapture_nx.kernel.paths import resolve_repo_path
from autocapture_nx.plugin_system.registry import PluginRegistry
from autocapture_nx.ux.fixture import (
    audit_fixture_event,
    build_query_specs,
    build_user_config,
    collect_plugin_load_report,
    collect_plugin_trace,
    evaluate_query,
    load_manifest,
    probe_plugins,
    resolve_screenshots,
    run_idle_processing,
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _resolve_path(path: str | Path) -> Path:
    raw = str(path)
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    if ":" in raw[:3]:
        return Path(raw)
    return resolve_repo_path(candidate)


def _replace_placeholder(value: Any, placeholder: str, replacement: str) -> Any:
    if isinstance(value, dict):
        return {k: _replace_placeholder(v, placeholder, replacement) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_placeholder(v, placeholder, replacement) for v in value]
    if isinstance(value, str):
        return value.replace(placeholder, replacement)
    return value


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _discover_plugins(base_config: dict) -> list[str]:
    registry = PluginRegistry(base_config, safe_mode=False)
    plugin_ids: list[str] = []
    for manifest_path in registry.discover_manifest_paths():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        plugin_id = str(payload.get("plugin_id") or "").strip()
        if plugin_id:
            plugin_ids.append(plugin_id)
    plugin_ids.sort()
    return plugin_ids


def _ensure_frames(frames_dir: Path, source_frame: Path) -> None:
    frames_dir.mkdir(parents=True, exist_ok=True)
    for stamp in ("113519", "113529", "113539"):
        dest = frames_dir / f"Screenshot 2026-02-02 {stamp}.png"
        if not dest.exists():
            dest.write_bytes(source_frame.read_bytes())


def _check_tesseract() -> dict[str, Any]:
    info = {"available": False, "version": None}
    try:
        proc = subprocess.run(["tesseract", "--version"], check=True, capture_output=True, text=True)
        info["available"] = True
        info["version"] = proc.stdout.splitlines()[0] if proc.stdout else "unknown"
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def _check_rapidocr() -> dict[str, Any]:
    info = {"available": False}
    try:
        import rapidocr_onnxruntime  # noqa: F401

        info["available"] = True
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


class Timeout(Exception):
    pass


def _with_timeout(seconds: int, fn: Callable[[], Any]) -> Any:
    def _handle(signum, frame):
        raise Timeout(f"timeout after {seconds}s")

    old = signal.signal(signal.SIGALRM, _handle)
    signal.alarm(seconds)
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def _probe_with_timeout(system: Any, sample_frame: bytes | None, sample_record_id: str | None, timeout_s: int) -> list[dict[str, Any]]:
    def _run_probe():
        return probe_plugins(system, sample_frame=sample_frame, sample_record_id=sample_record_id)

    try:
        return _with_timeout(timeout_s, _run_probe)
    except Exception as exc:
        return [{"capability": "probe_plugins", "provider_id": None, "ok": False, "error": f"{type(exc).__name__}: {exc}"}]


def main(argv: list[str] | None = None) -> int:
    if not os.environ.get("AUTOCAPTURE_PYTHON_EXE"):
        os.environ["AUTOCAPTURE_PYTHON_EXE"] = sys.executable
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="docs/test sample/fixture_manifest.json")
    parser.add_argument("--output-dir", default="artifacts/fixture_runs")
    parser.add_argument("--config-template", default="tools/fixture_config_template.json")
    parser.add_argument("--capture-timeout-s", type=float, default=15.0)
    parser.add_argument("--idle-timeout-s", type=float, default=90.0)
    parser.add_argument("--idle-max-steps", type=int, default=20)
    parser.add_argument("--probe-timeout-s", type=int, default=20)
    parser.add_argument("--force-idle", action="store_true")
    args = parser.parse_args(argv)

    manifest_path = _resolve_path(args.manifest)
    manifest = load_manifest(manifest_path)
    screenshots = resolve_screenshots(manifest)
    if not screenshots:
        print("ERROR: no screenshots listed in manifest")
        return 2
    source_frame = screenshots[0]
    frames_dir = Path("/tmp/fixture_frames_jepa")
    _ensure_frames(frames_dir, source_frame)
    frame_files = [p for p in sorted(frames_dir.iterdir()) if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}]
    if not frame_files:
        print(f"ERROR: no frames found in {frames_dir}")
        return 2

    run_dir = _resolve_path(args.output_dir) / f"stepwise_{_utc_stamp()}"
    config_dir = run_dir / "config"
    data_dir = run_dir / "data"
    run_id = f"fixture_{run_dir.name}"
    report_path = run_dir / "stepwise_report.json"

    def checkpoint() -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    def log(msg: str) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        line = f"[{stamp}] {msg}"
        print(line, flush=True)
        report.setdefault("log", []).append(line)
        checkpoint()

    report: dict[str, Any] = {
        "manifest": str(manifest_path),
        "run_dir": str(run_dir),
        "config_dir": str(config_dir),
        "data_dir": str(data_dir),
        "config_template": str(_resolve_path(args.config_template)),
        "frames_dir": str(frames_dir),
        "frame_count": len(frame_files),
        "run_id": run_id,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "stepwise": True,
    }
    checkpoint()

    report["deps"] = {"tesseract": _check_tesseract(), "rapidocr": _check_rapidocr()}
    log("deps_checked")

    user_config = build_user_config(
        args.config_template,
        frames_dir=frames_dir,
        max_frames=len(frame_files),
        run_id=run_id,
    )
    if isinstance(user_config, dict):
        storage_cfg = user_config.setdefault("storage", {})
        if isinstance(storage_cfg, dict):
            storage_cfg["data_dir"] = str(data_dir)
        plugins_cfg = user_config.setdefault("plugins", {})
        if isinstance(plugins_cfg, dict):
            settings_cfg = plugins_cfg.setdefault("settings", {})
            if isinstance(settings_cfg, dict):
                jepa_cfg = settings_cfg.setdefault("builtin.state.jepa.training", {})
                if isinstance(jepa_cfg, dict):
                    jepa_store = jepa_cfg.setdefault("storage", {})
                    if isinstance(jepa_store, dict):
                        jepa_store["data_dir"] = str(data_dir)
        user_config = _replace_placeholder(user_config, "{data_dir}", str(data_dir))
        if args.force_idle:
            runtime_cfg = user_config.setdefault("runtime", {})
            if isinstance(runtime_cfg, dict):
                enforce_cfg = runtime_cfg.setdefault("mode_enforcement", {})
                if isinstance(enforce_cfg, dict):
                    enforce_cfg["fixture_override"] = True
                    enforce_cfg["fixture_override_reason"] = "fixture_force_idle"

    base_config = _load_json(resolve_repo_path("config/default.json"))
    plugin_ids = _discover_plugins(base_config)
    plugins_cfg = user_config.setdefault("plugins", {})
    if isinstance(plugins_cfg, dict):
        plugins_cfg["allowlist"] = list(plugin_ids)
        plugins_cfg["enabled"] = {pid: True for pid in plugin_ids}

    config_dir.mkdir(parents=True, exist_ok=True)
    user_path = config_dir / "user.json"
    user_path.write_text(json.dumps(user_config, indent=2, sort_keys=True), encoding="utf-8")
    log("config_written")

    original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
    original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
    os.environ["AUTOCAPTURE_CONFIG_DIR"] = str(config_dir)
    os.environ["AUTOCAPTURE_DATA_DIR"] = str(data_dir)

    exit_code = 0
    kernel = None
    try:
        audit_fixture_event(
            "fixture.stepwise.start",
            outcome="ok",
            details={"run_id": run_id, "config_dir": str(config_dir)},
        )
        log("kernel_boot_start")
        kernel = Kernel(default_config_paths(), safe_mode=False)
        # Stepwise fixture validation is still a one-shot CLI flow; keep boot
        # lightweight to avoid WSL hangs/segfaults in integrity sweeps.
        system = _with_timeout(180, lambda: kernel.boot(start_conductor=False, fast_boot=True))
        log("kernel_boot_ok")
        report["plugins"] = {"load_report": collect_plugin_load_report(system)}
        log("plugin_load_report_ok")

        capture = system.get("capture.source") if system and hasattr(system, "get") else None
        if capture is None or not hasattr(capture, "start"):
            print("ERROR: capture.source unavailable")
            return 2
        log("capture_start")
        capture.start()
        metadata = system.get("storage.metadata")
        if metadata is None:
            print("ERROR: storage.metadata unavailable")
            return 2
        evidence_ids = []
        start = time.monotonic()
        while (time.monotonic() - start) <= float(args.capture_timeout_s):
            ids = []
            for key in getattr(metadata, "keys", lambda: [])():
                record = metadata.get(key, {})
                if isinstance(record, dict) and str(record.get("record_type", "")).startswith("evidence.capture."):
                    ids.append(str(key))
            if ids:
                evidence_ids = ids
                break
            time.sleep(0.1)
        capture.stop()
        log("capture_stop")
        report["evidence"] = {"count": len(evidence_ids), "record_ids": evidence_ids[:20]}
        log(f"evidence_count={len(evidence_ids)}")
        if not evidence_ids:
            exit_code = 3

        sample_frame = frame_files[0].read_bytes() if frame_files else None
        if exit_code == 0:
            log("idle_processing_start")
            idle_result = _with_timeout(
                int(args.idle_timeout_s) + 30,
                lambda: run_idle_processing(
                    system,
                    max_steps=int(args.idle_max_steps),
                    timeout_s=float(args.idle_timeout_s),
                ),
            )
            report["idle"] = idle_result
            log("idle_processing_done")
            if not idle_result.get("done") and idle_result.get("blocked"):
                exit_code = 4

        if exit_code == 0:
            sample_state = None
            record_type_counts: dict[str, int] = {}
            if metadata is not None:
                try:
                    for key in getattr(metadata, "keys", lambda: [])():
                        rec = metadata.get(key, {})
                        if isinstance(rec, dict) and rec.get("record_type") == "derived.sst.state":
                            ss = rec.get("screen_state") if isinstance(rec.get("screen_state"), dict) else {}
                            sample_state = {
                                "record_id": str(key),
                                "frame_id_top": rec.get("frame_id"),
                                "record_id_field": rec.get("record_id"),
                                "source_id": rec.get("source_id"),
                                "screen_frame_id": ss.get("frame_id"),
                                "screen_ts_ms": ss.get("ts_ms"),
                            }
                            break
                        if isinstance(rec, dict) and rec.get("record_type"):
                            rtype = str(rec.get("record_type"))
                            record_type_counts[rtype] = record_type_counts.get(rtype, 0) + 1
                except Exception as exc:
                    sample_state = {"error": f"{type(exc).__name__}: {exc}"}
            report["debug_state_record"] = sample_state
            report["debug_record_types"] = dict(sorted(record_type_counts.items()))
            log("debug_state_record_ok")
            log("query_start")
            specs = build_query_specs(manifest, metadata)
            query_results = []
            failures = 0
            if specs:
                for spec in specs:
                    result = evaluate_query(system, spec)
                    if not result.get("ok"):
                        failures += 1
                    query_results.append(result)
            report["queries"] = {"count": len(specs), "failures": failures, "results": query_results}
            log(f"query_done count={len(specs)} failures={failures}")
            if not specs or failures:
                exit_code = 5

        log("plugin_probe_start")
        report["plugin_probe"] = _probe_with_timeout(
            system,
            sample_frame=sample_frame,
            sample_record_id=(evidence_ids[0] if evidence_ids else None),
            timeout_s=int(args.probe_timeout_s),
        )
        log("plugin_probe_done")
        report["plugin_trace"] = collect_plugin_trace(system)
        log("plugin_trace_done")

    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        exit_code = 1
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        checkpoint()
        if kernel is not None:
            try:
                kernel.shutdown()
            except Exception:
                pass
        if original_config is None:
            os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
        else:
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = original_config
        if original_data is None:
            os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
        else:
            os.environ["AUTOCAPTURE_DATA_DIR"] = original_data

    print(f"STEPWISE_EXIT={exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
