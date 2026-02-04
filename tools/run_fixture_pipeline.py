"""Run fixture screenshot through capture + processing + query pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _collect_evidence(metadata) -> list[str]:
    ids = []
    for key in getattr(metadata, "keys", lambda: [])():
        record = metadata.get(key, {})
        if not isinstance(record, dict):
            continue
        record_type = str(record.get("record_type", ""))
        if record_type.startswith("evidence.capture."):
            ids.append(str(key))
    return sorted(ids)


def _wait_for_evidence(metadata, *, timeout_s: float = 10.0) -> list[str]:
    start = time.monotonic()
    while (time.monotonic() - start) <= timeout_s:
        ids = _collect_evidence(metadata)
        if ids:
            return ids
        time.sleep(0.1)
    return []


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _replace_placeholder(value: Any, placeholder: str, replacement: str) -> Any:
    if isinstance(value, dict):
        return {k: _replace_placeholder(v, placeholder, replacement) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_placeholder(v, placeholder, replacement) for v in value]
    if isinstance(value, str):
        return value.replace(placeholder, replacement)
    return value


def _ocr_report(system) -> dict:
    report = {"provider_ids": []}
    try:
        for plugin in getattr(system, "plugins", []):
            if not getattr(plugin, "capabilities", None):
                continue
            if "ocr.engine" in plugin.capabilities:
                report["provider_ids"].append(str(plugin.plugin_id))
    except Exception:
        pass
    cfg = getattr(system, "config", {}) if system is not None else {}
    models_cfg = cfg.get("models", {}) if isinstance(cfg, dict) else {}
    report["ocr_path"] = models_cfg.get("ocr_path")
    try:
        import pytesseract  # type: ignore

        try:
            ver = pytesseract.get_tesseract_version()
        except Exception:
            ver = None
        report["tesseract_available"] = bool(ver)
        report["tesseract_version"] = str(ver) if ver else None
    except Exception:
        report["tesseract_available"] = False
    try:
        import rapidocr_onnxruntime  # noqa: F401

        report["rapidocr_available"] = True
    except Exception:
        report["rapidocr_available"] = False
    if report.get("tesseract_available"):
        report["selected_backend"] = "tesseract"
    elif report.get("rapidocr_available"):
        report["selected_backend"] = "rapidocr_unconfigured"
    else:
        report["selected_backend"] = "basic"
    return report


def _validate_localhost(user_config: dict) -> tuple[bool, str]:
    web_cfg = user_config.get("web", {}) if isinstance(user_config, dict) else {}
    bind_host = str(web_cfg.get("bind_host", "") or "")
    allow_remote = bool(web_cfg.get("allow_remote", False))
    if allow_remote:
        return False, "web.allow_remote must be false"
    if bind_host and bind_host != "127.0.0.1":
        return False, f"web.bind_host must be 127.0.0.1 (got {bind_host})"
    return True, ""


def _validate_storage_policy(user_config: dict) -> tuple[bool, str]:
    storage_cfg = user_config.get("storage", {}) if isinstance(user_config, dict) else {}
    if not bool(storage_cfg.get("no_deletion_mode", False)):
        return False, "storage.no_deletion_mode must be true"
    if not bool(storage_cfg.get("raw_first_local", False)):
        return False, "storage.raw_first_local must be true"
    return True, ""


def _discover_plugins(base_config: dict) -> list[dict[str, Any]]:
    registry = PluginRegistry(base_config, safe_mode=False)
    manifests = []
    for manifest_path in registry.discover_manifest_paths():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        plugin_id = str(payload.get("plugin_id") or "").strip()
        if not plugin_id:
            continue
        manifests.append(
            {
                "plugin_id": plugin_id,
                "manifest_path": str(manifest_path),
                "enabled_default": bool(payload.get("enabled", True)),
                "permissions": payload.get("permissions", {}),
            }
        )
    manifests.sort(key=lambda item: item["plugin_id"])
    return manifests


def _build_plugin_status(
    *,
    manifests: list[dict[str, Any]],
    load_report: dict[str, Any],
    probe_results: list[dict[str, Any]],
    trace: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    loaded = set(load_report.get("loaded", []) if isinstance(load_report, dict) else [])
    failed = set(load_report.get("failed", []) if isinstance(load_report, dict) else [])
    skipped = set(load_report.get("skipped", []) if isinstance(load_report, dict) else [])
    errors = load_report.get("errors", []) if isinstance(load_report, dict) else []
    error_map: dict[str, list[dict[str, Any]]] = {}
    for err in errors:
        if not isinstance(err, dict):
            continue
        pid = str(err.get("plugin_id") or "").strip()
        if not pid:
            continue
        error_map.setdefault(pid, []).append(err)

    trace_summary = trace.get("summary", {}) if isinstance(trace, dict) else {}
    trace_plugins = trace_summary.get("plugins", {}) if isinstance(trace_summary, dict) else {}
    probe_by_plugin: dict[str, list[dict[str, Any]]] = {}
    for entry in probe_results:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("provider_id") or "").strip()
        if not pid:
            continue
        probe_by_plugin.setdefault(pid, []).append(entry)

    statuses: list[dict[str, Any]] = []
    skipped_without_reason: list[str] = []
    for item in manifests:
        pid = item["plugin_id"]
        status = "unknown"
        if pid in loaded:
            status = "loaded"
        elif pid in failed:
            status = "failed"
        elif pid in skipped:
            status = "skipped"
        reasons = error_map.get(pid, [])
        probe = probe_by_plugin.get(pid, [])
        trace_info = trace_plugins.get(pid, {"calls": 0, "errors": 0})
        if status == "skipped" and not reasons:
            skipped_without_reason.append(pid)
        if status == "unknown":
            skipped_without_reason.append(pid)
        statuses.append(
            {
                "plugin_id": pid,
                "status": status,
                "errors": reasons,
                "probe": probe,
                "trace": trace_info,
            }
        )
    return statuses, skipped_without_reason


def main(argv: list[str] | None = None) -> int:
    if not os.environ.get("AUTOCAPTURE_PYTHON_EXE"):
        os.environ["AUTOCAPTURE_PYTHON_EXE"] = sys.executable
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="docs/test sample/fixture_manifest.json")
    parser.add_argument("--output-dir", default="artifacts/fixture_runs")
    parser.add_argument("--config-template", default="tools/fixture_config_template.json")
    parser.add_argument("--capture-timeout-s", type=float, default=10.0)
    parser.add_argument("--idle-timeout-s", type=float, default=60.0)
    parser.add_argument("--idle-max-steps", type=int, default=20)
    parser.add_argument("--input-dir", default="")
    parser.add_argument("--force-idle", action="store_true")
    args = parser.parse_args(argv)

    manifest_path = _resolve_path(args.manifest)
    manifest = load_manifest(manifest_path)
    screenshots = resolve_screenshots(manifest)
    if not screenshots:
        print("ERROR: no screenshots listed in manifest")
        return 2
    if args.input_dir:
        frames_dir = _resolve_path(args.input_dir)
    else:
        frames_dir = screenshots[0].parent
    if not frames_dir.exists():
        print(f"ERROR: frames_dir not found: {frames_dir}")
        return 2
    frame_files = [p for p in sorted(frames_dir.iterdir()) if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}]
    if not frame_files:
        print(f"ERROR: no frames found in {frames_dir}")
        return 2

    run_dir = _resolve_path(args.output_dir) / _utc_stamp()
    config_dir = run_dir / "config"
    data_dir = run_dir / "data"
    run_id = f"fixture_{run_dir.name}"

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
                    storage_cfg = jepa_cfg.setdefault("storage", {})
                    if isinstance(storage_cfg, dict):
                        storage_cfg["data_dir"] = str(data_dir)
        user_config = _replace_placeholder(user_config, "{data_dir}", str(data_dir))
    if args.force_idle and isinstance(user_config, dict):
        runtime_cfg = user_config.setdefault("runtime", {})
        if isinstance(runtime_cfg, dict):
            enforce_cfg = runtime_cfg.setdefault("mode_enforcement", {})
            if isinstance(enforce_cfg, dict):
                enforce_cfg["fixture_override"] = True
                enforce_cfg["fixture_override_reason"] = "fixture_force_idle"

    ok_localhost, err_localhost = _validate_localhost(user_config)
    if not ok_localhost:
        print(f"ERROR: {err_localhost}")
        return 2
    ok_storage, err_storage = _validate_storage_policy(user_config)
    if not ok_storage:
        print(f"ERROR: {err_storage}")
        return 2
    base_config = _load_json(resolve_repo_path("config/default.json"))
    manifests = _discover_plugins(base_config)
    plugin_ids = [item["plugin_id"] for item in manifests]
    plugins_cfg = user_config.setdefault("plugins", {})
    if isinstance(plugins_cfg, dict):
        plugins_cfg["allowlist"] = list(plugin_ids)
        plugins_cfg["enabled"] = {pid: True for pid in plugin_ids}
    config_dir.mkdir(parents=True, exist_ok=True)
    user_path = (config_dir / "user.json")
    user_path.write_text(json.dumps(user_config, indent=2, sort_keys=True), encoding="utf-8")
    config_hash = _sha256_text(user_path.read_text(encoding="utf-8"))

    audit_fixture_event(
        "fixture.config.override",
        outcome="ok",
        details={
            "manifest": str(manifest_path),
            "frames_dir": str(frames_dir),
            "run_id": run_id,
            "config_hash": config_hash,
        },
    )
    if args.force_idle:
        audit_fixture_event(
            "fixture.force_idle",
            outcome="ok",
            details={
                "run_id": run_id,
                "config_hash": config_hash,
            },
        )

    original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
    original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
    os.environ["AUTOCAPTURE_CONFIG_DIR"] = str(config_dir)
    os.environ["AUTOCAPTURE_DATA_DIR"] = str(data_dir)

    report: dict[str, object] = {
        "manifest": str(manifest_path),
        "run_dir": str(run_dir),
        "config_dir": str(config_dir),
        "data_dir": str(data_dir),
        "config_template": str(_resolve_path(args.config_template)),
        "frames_dir": str(frames_dir),
        "frame_count": len(frame_files),
        "run_id": run_id,
        "config_hash": config_hash,
        "started_utc": datetime.now(timezone.utc).isoformat(),
    }

    exit_code = 0
    kernel = None
    try:
        audit_fixture_event(
            "fixture.run.start",
            outcome="ok",
            details={
                "manifest": str(manifest_path),
                "frames_dir": str(frames_dir),
                "run_id": run_id,
                "config_hash": config_hash,
            },
        )
        kernel = Kernel(default_config_paths(), safe_mode=False)
        system = kernel.boot(start_conductor=False)
        report["ocr"] = _ocr_report(system)
        report["plugins"] = {"load_report": collect_plugin_load_report(system)}

        capture = system.get("capture.source") if system and hasattr(system, "get") else None
        if capture is None or not hasattr(capture, "start"):
            print("ERROR: capture.source unavailable")
            return 2
        capture.start()
        metadata = system.get("storage.metadata")
        if metadata is None:
            print("ERROR: storage.metadata unavailable")
            return 2
        evidence_ids = _wait_for_evidence(metadata, timeout_s=float(args.capture_timeout_s))
        if not evidence_ids:
            print("ERROR: no evidence captured")
            exit_code = 3
        capture.stop()
        report["evidence"] = {"count": len(evidence_ids), "record_ids": evidence_ids[:20]}
        sample_frame = None
        try:
            if frame_files:
                sample_frame = frame_files[0].read_bytes()
        except Exception:
            sample_frame = None

        if exit_code == 0:
            idle_result = run_idle_processing(
                system,
                max_steps=int(args.idle_max_steps),
                timeout_s=float(args.idle_timeout_s),
            )
            report["idle"] = idle_result
            if not idle_result.get("done") and idle_result.get("blocked"):
                exit_code = 4

        if exit_code == 0:
            specs = build_query_specs(manifest, metadata)
            query_results = []
            failures = 0
            if not specs:
                report["queries"] = {"count": 0, "failures": 1, "results": []}
                exit_code = 5
            else:
                for spec in specs:
                    result = evaluate_query(system, spec)
                    if not result.get("ok"):
                        failures += 1
                    query_results.append(result)
                report["queries"] = {"count": len(specs), "failures": failures, "results": query_results}
                if failures:
                    exit_code = 5
        report["plugin_probe"] = probe_plugins(
            system,
            sample_frame=sample_frame,
            sample_record_id=(evidence_ids[0] if evidence_ids else None),
        )
        report["plugin_trace"] = collect_plugin_trace(system)
        plugin_status, skipped_without_reason = _build_plugin_status(
            manifests=manifests,
            load_report=report["plugins"]["load_report"],
            probe_results=report["plugin_probe"],
            trace=report["plugin_trace"],
        )
        report["plugin_status"] = plugin_status
        report["skipped_without_reason"] = skipped_without_reason
        if skipped_without_reason and exit_code == 0:
            exit_code = 6

    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        exit_code = 1
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            output_path = run_dir / "fixture_report.json"
            output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
            report["report_path"] = str(output_path)
        except Exception:
            pass
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

    audit_fixture_event(
        "fixture.run.finish",
        outcome="ok" if exit_code == 0 else "error",
        details={
            "manifest": str(manifest_path),
            "run_id": run_id,
            "exit_code": exit_code,
            "run_dir": str(run_dir),
        },
    )

    if report.get("plugin_status"):
        print("PLUGIN STATUS:")
        for entry in report.get("plugin_status", []):
            if not isinstance(entry, dict):
                continue
            pid = entry.get("plugin_id")
            status = entry.get("status")
            errors = entry.get("errors") or []
            msg = f"- {pid}: {status}"
            if errors:
                msg += f" ({len(errors)} errors)"
            print(msg)

    if exit_code == 0:
        print("OK: fixture pipeline")
    else:
        print(f"FAIL: fixture pipeline (code {exit_code})")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
