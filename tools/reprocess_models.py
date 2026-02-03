"""Reprocess existing evidence with updated models and emit plugin reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

from autocapture_nx.kernel.audit import append_audit_event
from autocapture_nx.kernel.loader import Kernel, default_config_paths
from autocapture_nx.kernel.paths import resolve_repo_path
from autocapture_nx.plugin_system.registry import PluginRegistry
from autocapture_nx.ux.fixture import (
    collect_plugin_load_report,
    collect_plugin_trace,
    probe_plugins,
    run_idle_processing,
)
from autocapture_nx.processing.idle import _extract_frame, _get_media_blob  # type: ignore


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


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _join_model_path(root_dir: str, *parts: str) -> str:
    if ":" in root_dir[:3]:
        base = PureWindowsPath(root_dir)
        for part in parts:
            if part:
                base = base / part
        return str(base)
    return str(Path(root_dir, *[p for p in parts if p]))


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_localhost(user_config: dict[str, Any]) -> tuple[bool, str]:
    web_cfg = user_config.get("web", {}) if isinstance(user_config, dict) else {}
    bind_host = str(web_cfg.get("bind_host", "") or "")
    allow_remote = bool(web_cfg.get("allow_remote", False))
    if allow_remote:
        return False, "web.allow_remote must be false"
    if bind_host and bind_host != "127.0.0.1":
        return False, f"web.bind_host must be 127.0.0.1 (got {bind_host})"
    return True, ""


def _validate_storage_policy(user_config: dict[str, Any]) -> tuple[bool, str]:
    storage_cfg = user_config.get("storage", {}) if isinstance(user_config, dict) else {}
    if not bool(storage_cfg.get("no_deletion_mode", False)):
        return False, "storage.no_deletion_mode must be true"
    if not bool(storage_cfg.get("raw_first_local", False)):
        return False, "storage.raw_first_local must be true"
    return True, ""


def _discover_plugins(base_config: dict[str, Any]) -> list[dict[str, Any]]:
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


def _apply_model_manifest(
    *,
    user_config: dict[str, Any],
    manifest: dict[str, Any],
    root_dir_override: str | None,
) -> None:
    if not isinstance(manifest, dict):
        return
    root_dir = str(root_dir_override or manifest.get("root_dir") or "").strip()
    if not root_dir:
        return
    models_cfg = user_config.setdefault("models", {})
    if not isinstance(models_cfg, dict):
        return
    providers_cfg = models_cfg.setdefault("providers", {})
    if not isinstance(providers_cfg, dict):
        return
    plugin_settings = user_config.setdefault("plugins", {}).setdefault("settings", {})
    if not isinstance(plugin_settings, dict):
        return

    hf_models = manifest.get("huggingface", {}).get("models", [])
    if not isinstance(hf_models, list):
        return
    for model in hf_models:
        if not isinstance(model, dict):
            continue
        provider_id = str(model.get("provider_id") or "").strip()
        model_id = str(model.get("id") or "").strip()
        subdir = str(model.get("subdir") or "").strip()
        if not provider_id or not model_id or not subdir:
            continue
        model_path = _join_model_path(root_dir, subdir)
        provider_meta = {
            "model_id": model_id,
            "model_path": model_path,
            "revision": model.get("revision") or "",
        }
        if isinstance(model.get("files"), dict):
            provider_meta["files"] = model.get("files")
        providers_cfg[provider_id] = provider_meta

        settings = plugin_settings.setdefault(provider_id, {})
        if not isinstance(settings, dict):
            continue
        models = settings.setdefault("models", {})
        if not isinstance(models, dict):
            continue
        if model.get("kind") == "vlm":
            models["vlm_path"] = model_path
            if model.get("prompt"):
                models["vlm_prompt"] = model.get("prompt")
            if model.get("max_new_tokens"):
                models["vlm_max_new_tokens"] = int(model.get("max_new_tokens") or 0) or 160
            if "vlm_prompt" not in models:
                models["vlm_prompt"] = "Extract visible UI text, window titles, apps, and key screen details."
        if model.get("kind") == "ocr":
            files = model.get("files") or {}
            if isinstance(files, dict):
                rapid_cfg = models.setdefault("rapidocr", {})
                if isinstance(rapid_cfg, dict):
                    rapid_cfg["det_model_path"] = _join_model_path(root_dir, subdir, str(files.get("det") or ""))
                    rapid_cfg["rec_model_path"] = _join_model_path(root_dir, subdir, str(files.get("rec") or ""))
                    rapid_cfg["cls_model_path"] = _join_model_path(root_dir, subdir, str(files.get("cls") or ""))
                    if files.get("keys"):
                        rapid_cfg["rec_keys_path"] = _join_model_path(root_dir, subdir, str(files.get("keys")))
                    rapid_cfg.setdefault("use_cuda", True)


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output-dir", default="artifacts/reprocess_runs")
    parser.add_argument("--config-template", default="tools/reprocess_config_template.json")
    parser.add_argument("--model-manifest", default="tools/model_manifest.json")
    parser.add_argument("--force-idle", action="store_true")
    parser.add_argument("--idle-timeout-s", type=float, default=300.0)
    parser.add_argument("--idle-max-steps", type=int, default=200)
    parser.add_argument("--model-root", default="")
    args = parser.parse_args(argv)

    run_dir = _resolve_path(args.output_dir) / _utc_stamp()
    config_dir = run_dir / "config"
    data_dir = _resolve_path(args.data_dir)
    if not data_dir.exists():
        print(f"ERROR: data dir not found: {data_dir}")
        return 2
    run_id = f"reprocess_{run_dir.name}"

    template_path = _resolve_path(args.config_template)
    user_config = _load_json(template_path)
    if isinstance(user_config, dict):
        runtime_cfg = user_config.setdefault("runtime", {})
        if isinstance(runtime_cfg, dict):
            runtime_cfg["run_id"] = run_id
            if args.force_idle:
                enforce = runtime_cfg.setdefault("mode_enforcement", {})
                if isinstance(enforce, dict):
                    enforce["fixture_override"] = True
                    enforce["fixture_override_reason"] = "reprocess_force_idle"
        if args.force_idle:
            append_audit_event(
                action="reprocess.force_idle",
                actor="tools.reprocess",
                outcome="ok",
                details={"run_id": run_id, "data_dir": str(data_dir)},
            )

    model_manifest_path = _resolve_path(args.model_manifest)
    if model_manifest_path.exists():
        manifest = _load_json(model_manifest_path)
        _apply_model_manifest(
            user_config=user_config,
            manifest=manifest,
            root_dir_override=args.model_root or None,
        )
    else:
        manifest = {}

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
    user_path = config_dir / "user.json"
    user_path.write_text(json.dumps(user_config, indent=2, sort_keys=True), encoding="utf-8")
    config_hash = _sha256_text(user_path.read_text(encoding="utf-8"))

    report: dict[str, Any] = {
        "run_dir": str(run_dir),
        "data_dir": str(data_dir),
        "config_dir": str(config_dir),
        "config_template": str(template_path),
        "run_id": run_id,
        "config_hash": config_hash,
        "manifest_path": str(model_manifest_path),
        "started_utc": datetime.now(timezone.utc).isoformat(),
    }

    original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
    original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
    os.environ["AUTOCAPTURE_CONFIG_DIR"] = str(config_dir)
    os.environ["AUTOCAPTURE_DATA_DIR"] = str(data_dir)

    exit_code = 0
    kernel = None
    try:
        append_audit_event(
            action="reprocess.start",
            actor="tools.reprocess",
            outcome="ok",
            details={
                "run_id": run_id,
                "data_dir": str(data_dir),
                "config_hash": config_hash,
                "manifest": str(model_manifest_path),
            },
        )
        kernel = Kernel(default_config_paths(), safe_mode=False)
        system = kernel.boot(start_conductor=False)

        report["plugins"] = {"load_report": collect_plugin_load_report(system)}
        idle_result = run_idle_processing(
            system,
            max_steps=int(args.idle_max_steps),
            timeout_s=float(args.idle_timeout_s),
        )
        report["idle"] = idle_result
        if not idle_result.get("done") and idle_result.get("blocked"):
            exit_code = 4

        sample_frame = None
        sample_record_id = None
        metadata = system.get("storage.metadata") if system and hasattr(system, "get") else None
        media = system.get("storage.media") if system and hasattr(system, "get") else None
        if metadata is not None:
            try:
                keys = list(getattr(metadata, "keys", lambda: [])())
                for key in sorted(keys):
                    record = metadata.get(key, {})
                    if isinstance(record, dict) and str(record.get("record_type", "")).startswith("evidence.capture."):
                        sample_record_id = str(key)
                        if media is not None:
                            blob = _get_media_blob(media, sample_record_id)
                            if blob:
                                sample_frame = _extract_frame(blob, record)
                        break
            except Exception:
                sample_record_id = None
        report["plugin_probe"] = probe_plugins(
            system,
            sample_frame=sample_frame,
            sample_record_id=sample_record_id,
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
            output_path = run_dir / "reprocess_report.json"
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

    append_audit_event(
        action="reprocess.finish",
        actor="tools.reprocess",
        outcome="ok" if exit_code == 0 else "error",
        details={
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
        print("OK: reprocess models")
    else:
        print(f"FAIL: reprocess models (code {exit_code})")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
