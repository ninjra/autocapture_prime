"""Ingest and process a single screenshot without capture/input plugins.

Purpose:
- Debug/validate the WSL-side processing pipeline when capture happens elsewhere.
- Ensure processing does not crash when input tracking records are absent.

This script:
1) Boots the kernel against a fresh ephemeral DataRoot under artifacts/
2) Writes one evidence.capture.frame record + stores the image bytes in media store
3) Runs idle processing (OCR/VLM/SST/state as configured) under fixture override
4) Optionally runs a query and writes a JSON report

It does NOT attempt any screen capture, window hooks, or input hooks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.ids import ensure_run_id, prefixed_id
from autocapture_nx.kernel.loader import Kernel, default_config_paths
from autocapture_nx.kernel.paths import resolve_repo_path
from dataclasses import asdict

from autocapture_nx.inference.vllm_endpoint import EXTERNAL_VLLM_BASE_URL, check_external_vllm_ready
from autocapture_nx.kernel.providers import capability_providers
from autocapture_nx.kernel.query import run_query, run_query_without_state, run_state_query
from autocapture_nx.processing.idle import IdleProcessor
from autocapture_nx.ux.fixture import collect_plugin_load_report

STRICT_GOLDEN_ENV_BLOCKLIST: tuple[str, ...] = (
    "AUTOCAPTURE_DISABLE_REQUIRED_PLUGIN_GATE",
    "AUTOCAPTURE_IDLE_VLM_EXTRACT",
    "AUTOCAPTURE_QWEN_MAX_ROIS",
    "AUTOCAPTURE_QWEN_MODEL",
    "AUTOCAPTURE_QWEN_ROI_MAX_NEW_TOKENS",
    "AUTOCAPTURE_QWEN_ROI_MAX_SIDE",
    "AUTOCAPTURE_QWEN_THUMB_MAX_NEW_TOKENS",
    "AUTOCAPTURE_VLM_MAX_ROIS",
    "AUTOCAPTURE_VLM_MAX_TOKENS",
    "AUTOCAPTURE_VLM_ROI_MAX_SIDE",
    "AUTOCAPTURE_VLM_ROI_MAX_TOKENS",
    "AUTOCAPTURE_VLM_THUMB_MAX_PX",
    "AUTOCAPTURE_VLM_THUMB_MAX_TOKENS",
    "AUTOCAPTURE_VLM_TIMEOUT_S",
)
CORE_WRITER_PLUGINS: tuple[str, ...] = (
    "builtin.journal.basic",
    "builtin.ledger.basic",
    "builtin.anchor.basic",
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _emit_progress(stage: str, **fields: Any) -> None:
    payload: dict[str, Any] = {
        "event": "process_single_screenshot.progress",
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "stage": str(stage),
    }
    payload.update(fields)
    try:
        print(json.dumps(payload, sort_keys=True), file=sys.stderr, flush=True)
    except Exception:
        pass


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _configured_vlm_api_key_from_config(path: Path) -> str:
    try:
        raw = _load_json(path)
    except Exception:
        return ""
    plugins_cfg = raw.get("plugins", {}) if isinstance(raw, dict) else {}
    settings = plugins_cfg.get("settings", {}) if isinstance(plugins_cfg, dict) else {}
    if not isinstance(settings, dict):
        return ""
    for plugin_id in (
        "builtin.vlm.vllm_localhost",
        "builtin.answer.synth_vllm_localhost",
        "builtin.ocr.nemotron_torch",
    ):
        cfg = settings.get(plugin_id, {})
        if not isinstance(cfg, dict):
            continue
        key = str(cfg.get("api_key") or "").strip()
        if key:
            return key
    return ""


def _repo_default_vlm_api_key() -> str:
    return _configured_vlm_api_key_from_config(resolve_repo_path("config/user.json"))


def _image_size(image_bytes: bytes) -> tuple[int, int]:
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return 0, 0
    try:
        from io import BytesIO

        img = Image.open(BytesIO(image_bytes))
        w, h = img.size
        return int(w or 0), int(h or 0)
    except Exception:
        return 0, 0


def _guess_content_type(blob: bytes) -> str:
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if blob.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return "application/octet-stream"


def _build_frame_record(*, run_id: str, record_id: str, ts_utc: str, image_bytes: bytes) -> dict[str, Any]:
    width, height = _image_size(image_bytes)
    content_hash = hashlib.sha256(image_bytes).hexdigest()
    payload: dict[str, Any] = {
        "record_type": "evidence.capture.frame",
        "run_id": run_id,
        "ts_utc": ts_utc,
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}" if width and height else "",
        "content_type": _guess_content_type(image_bytes),
        "content_size": int(len(image_bytes)),
        "content_hash": content_hash,
        "image_sha256": content_hash,
        "frame_index": 0,
        "source": "tools.process_single_screenshot",
    }
    payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
    return payload


def _record_with_payload_hash(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["payload_hash"] = sha256_canonical({k: v for k, v in out.items() if k != "payload_hash"})
    return out


def _parse_ts_utc(value: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _to_utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_idle_step_max_seconds(*, budget_ms: int) -> int:
    raw = str(os.environ.get("AUTOCAPTURE_SINGLE_IDLE_STEP_MAX_SECONDS") or "").strip()
    try:
        env_val = int(raw) if raw else 0
    except Exception:
        env_val = 0
    if env_val > 0:
        return max(15, min(600, env_val))
    budget_s = max(1, int((int(budget_ms) + 999) // 1000))
    return max(30, min(120, budget_s))


def _metadata_put(metadata: Any, record_id: str, payload: dict[str, Any]) -> None:
    if hasattr(metadata, "put_new"):
        try:
            _safe_call(metadata, "put_new", record_id, payload)
            return
        except Exception:
            pass
    _safe_call(metadata, "put", record_id, payload)


def _append_journal_event(journal: Any | None, *, event_type: str, payload: dict[str, Any], ts_utc: str) -> bool:
    if journal is None:
        return False
    try:
        if hasattr(journal, "append_event"):
            _safe_call(journal, "append_event", event_type, payload, ts_utc=ts_utc)
            return True
        entry = {
            "schema_version": 1,
            "event_id": "",
            "sequence": None,
            "ts_utc": ts_utc,
            "tzid": "UTC",
            "offset_minutes": 0,
            "event_type": event_type,
            "payload": payload,
            "run_id": str(payload.get("run_id") or ""),
        }
        _safe_call(journal, "append", entry)
        return True
    except Exception:
        return False


def _inject_synthetic_hid(
    *,
    metadata: Any,
    journal: Any | None,
    run_id: str,
    base_ts_utc: str,
    mode: str,
) -> dict[str, Any]:
    start_dt = _parse_ts_utc(base_ts_utc)
    events: list[dict[str, Any]] = [
        {"kind": "key", "action": "press", "key": "ctrl", "ts_utc": _to_utc_z(start_dt)},
        {"kind": "key", "action": "press", "key": "k", "ts_utc": _to_utc_z(start_dt)},
        {"kind": "mouse", "action": "move", "x": 768, "y": 432, "ts_utc": _to_utc_z(start_dt)},
        {"kind": "mouse", "action": "click", "button": "left", "x": 768, "y": 432, "ts_utc": _to_utc_z(start_dt)},
    ]
    cursor_points: list[dict[str, Any]] = [
        {"x": 740, "y": 410},
        {"x": 768, "y": 432},
        {"x": 812, "y": 460},
    ]
    if mode == "rich":
        events.extend(
            [
                {"kind": "key", "action": "press", "key": "alt", "ts_utc": _to_utc_z(start_dt)},
                {"kind": "key", "action": "press", "key": "tab", "ts_utc": _to_utc_z(start_dt)},
                {"kind": "mouse", "action": "wheel", "delta": -120, "x": 1730, "y": 980, "ts_utc": _to_utc_z(start_dt)},
                {"kind": "mouse", "action": "click", "button": "left", "x": 1730, "y": 980, "ts_utc": _to_utc_z(start_dt)},
            ]
        )
        cursor_points.extend([{"x": 1320, "y": 620}, {"x": 1730, "y": 980}])

    key_count = sum(1 for item in events if str(item.get("kind")) == "key")
    mouse_count = sum(1 for item in events if str(item.get("kind")) == "mouse")
    end_dt = start_dt
    if events:
        end_dt = start_dt.replace(microsecond=0)
    summary_id = prefixed_id(run_id, "derived.input.summary", 0)
    summary_payload = _record_with_payload_hash(
        {
            "schema_version": 1,
            "record_type": "derived.input.summary",
            "run_id": run_id,
            "event_id": prefixed_id(run_id, "input.batch", 0),
            "start_ts_utc": _to_utc_z(start_dt),
            "end_ts_utc": _to_utc_z(end_dt),
            "event_count": int(len(events)),
            "counts": {"key": int(key_count), "mouse": int(mouse_count)},
            "events": events,
            "source": "tools.process_single_screenshot.synthetic_hid",
        }
    )
    _metadata_put(metadata, summary_id, summary_payload)
    cursor_ids: list[str] = []
    for idx, point in enumerate(cursor_points):
        cursor_id = prefixed_id(run_id, "derived.cursor.sample", idx)
        cursor_payload = _record_with_payload_hash(
            {
                "schema_version": 1,
                "record_type": "derived.cursor.sample",
                "run_id": run_id,
                "ts_utc": _to_utc_z(start_dt),
                "cursor": {"x": int(point.get("x", 0)), "y": int(point.get("y", 0))},
                "source": "tools.process_single_screenshot.synthetic_hid",
            }
        )
        _metadata_put(metadata, cursor_id, cursor_payload)
        cursor_ids.append(cursor_id)

    journal_events_written = 0
    input_payload = {
        "record_type": "derived.input.summary",
        "record_id": summary_id,
        "run_id": run_id,
        "start_ts_utc": summary_payload["start_ts_utc"],
        "end_ts_utc": summary_payload["end_ts_utc"],
        "events": events,
        "counts": summary_payload["counts"],
    }
    if _append_journal_event(journal, event_type="input.batch", payload=input_payload, ts_utc=summary_payload["end_ts_utc"]):
        journal_events_written += 1
    if cursor_ids:
        cursor_payload = {
            "record_type": "derived.cursor.sample",
            "record_id": cursor_ids[-1],
            "run_id": run_id,
            "cursor": {"x": int(cursor_points[-1]["x"]), "y": int(cursor_points[-1]["y"])},
        }
        if _append_journal_event(
            journal,
            event_type="cursor.sample",
            payload=cursor_payload,
            ts_utc=summary_payload["end_ts_utc"],
        ):
            journal_events_written += 1

    return {
        "enabled": True,
        "mode": mode,
        "metadata_record_ids": [summary_id] + cursor_ids,
        "journal_events_written": int(journal_events_written),
        "event_count": int(len(events)),
    }


def _safe_call(obj: Any, name: str, *args, **kwargs) -> Any:
    fn = getattr(obj, name, None)
    if fn is None or not callable(fn):
        raise RuntimeError(f"{type(obj).__name__} missing callable {name}()")
    return fn(*args, **kwargs)


_LIST_UNION_PATHS: tuple[str, ...] = (
    "plugins.allowlist",
    "plugins.permissions.localhost_allowed_plugin_ids",
    "plugins.hosting.inproc_allowlist",
)


def _deep_merge_dict(base: dict[str, Any], overlay: dict[str, Any], *, _path: str = "") -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overlay.items():
        next_path = f"{_path}.{key}" if _path else str(key)
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value, _path=next_path)
            continue
        if isinstance(value, list) and isinstance(merged.get(key), list) and next_path in _LIST_UNION_PATHS:
            merged_list = [str(item) for item in merged.get(key, [])]
            for item in value:
                text = str(item)
                if text not in merged_list:
                    merged_list.append(text)
            merged[key] = merged_list
            continue
        merged[key] = deepcopy(value)
    return merged


def _plugin_gate_status(load_report: dict[str, Any], required_plugins: list[str]) -> dict[str, Any]:
    loaded = {str(x).strip() for x in (load_report.get("loaded") or []) if str(x).strip()}
    failed = {str(x).strip() for x in (load_report.get("failed") or []) if str(x).strip()}
    required = [str(x).strip() for x in required_plugins if str(x).strip()]
    missing = sorted([plugin_id for plugin_id in required if plugin_id not in loaded and plugin_id not in failed])
    failed_required = sorted([plugin_id for plugin_id in required if plugin_id in failed])
    return {
        "required_plugins": required,
        "missing_required": missing,
        "failed_required": failed_required,
        "ok": not missing and not failed_required,
    }


def _should_stop_idle_loop(
    *,
    done: bool,
    stats: dict[str, Any],
    need_vlm: bool = False,
    need_sst: bool = False,
    need_state: bool = False,
) -> bool:
    vlm_ok = int(stats.get("vlm_ok", 0) or 0) > 0
    sst_ok = int(stats.get("sst_runs", 0) or 0) > 0
    state_ok = int(stats.get("state_runs", 0) or 0) > 0

    if need_vlm and not vlm_ok:
        return False
    if need_sst and not sst_ok:
        return False
    if need_state and not state_ok:
        return False
    if bool(done):
        return True
    return state_ok


def _should_require_vlm(required_plugins: list[str]) -> bool:
    required = {str(x).strip() for x in (required_plugins or []) if str(x).strip()}
    if "builtin.vlm.vllm_localhost" in required:
        return True
    forced = str(os.environ.get("AUTOCAPTURE_REQUIRE_VLM") or "").strip().casefold()
    return forced in {"1", "true", "yes"}


def _disable_vlm_idle_runtime(idle: Any) -> None:
    cfg = getattr(idle, "_config", None)
    if not isinstance(cfg, dict):
        return
    processing_cfg = cfg.setdefault("processing", {})
    if not isinstance(processing_cfg, dict):
        return
    idle_cfg = processing_cfg.setdefault("idle", {})
    if isinstance(idle_cfg, dict):
        extractors_cfg = idle_cfg.setdefault("extractors", {})
        if isinstance(extractors_cfg, dict):
            extractors_cfg["vlm"] = False
        idle_cfg["max_concurrency_gpu"] = 0
    sst_cfg = processing_cfg.setdefault("sst", {})
    if isinstance(sst_cfg, dict):
        sst_cfg["allow_vlm"] = False
        ui_vlm_cfg = sst_cfg.setdefault("ui_vlm", {})
        if isinstance(ui_vlm_cfg, dict):
            ui_vlm_cfg["enabled"] = False


def _is_truthy_env(value: str | None) -> bool:
    text = str(value or "").strip().casefold()
    if not text:
        return False
    return text not in {"0", "false", "no", "off", "none"}


def _ensure_core_writer_plugins(*, allowlist: list[str] | None = None, enabled: dict[str, Any] | None = None) -> None:
    if isinstance(allowlist, list):
        for plugin_id in CORE_WRITER_PLUGINS:
            if plugin_id not in allowlist:
                allowlist.append(plugin_id)
    if isinstance(enabled, dict):
        for plugin_id in CORE_WRITER_PLUGINS:
            enabled[plugin_id] = True


def _strict_golden_enabled() -> bool:
    return _is_truthy_env(os.environ.get("AUTOCAPTURE_GOLDEN_STRICT", "1"))


def _blocked_env_overrides(override_keys: list[str]) -> list[str]:
    blocked: list[str] = []
    for key in override_keys:
        if _is_truthy_env(os.environ.get(key)):
            blocked.append(str(key))
    return sorted(blocked)


def _coerce_int(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except Exception:
        return int(default)


def _coerce_float(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except Exception:
        return float(default)


def _resolve_strict_model_selection(*, selected_model: str, served_models: list[str], strict_golden: bool) -> tuple[str, str]:
    selected = str(selected_model or "").strip()
    models = [str(x).strip() for x in served_models if str(x).strip()]
    if not strict_golden:
        return selected, "configured"
    if selected:
        return selected, "configured"
    if len(models) == 1:
        return models[0], "auto_single_served_model"
    if len(models) > 1:
        raise RuntimeError(
            f"strict_golden_requires_explicit_vllm_model_multiple_available:{','.join(models)}"
        )
    raise RuntimeError("strict_golden_requires_vllm_models")


def _best_effort_finalize_run_state(
    data_dir: Path,
    *,
    error: str | None = None,
    terminated_signal: int | None = None,
) -> None:
    run_state_path = data_dir / "run_state.json"
    if not run_state_path.exists():
        return
    try:
        raw = json.loads(run_state_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(raw, dict):
        return
    now_utc = datetime.now(timezone.utc).isoformat()
    raw["state"] = "stopped"
    raw["stopped_at"] = now_utc
    raw["ts_utc"] = now_utc
    if error:
        raw["last_error"] = str(error)
    if terminated_signal is not None:
        raw["terminated_signal"] = int(terminated_signal)
    try:
        run_state_path.write_text(json.dumps(raw, sort_keys=True), encoding="utf-8")
    except Exception:
        return


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, help="Path to a PNG/JPG screenshot on disk.")
    parser.add_argument("--output-dir", default="artifacts/single_image_runs", help="Directory to write run artifacts.")
    parser.add_argument("--config-base", default="config/default.json", help="Base config JSON to load.")
    parser.add_argument(
        "--profile",
        default="config/profiles/golden_full.json",
        help="Optional config profile JSON overlay (golden pipeline defaults).",
    )
    parser.add_argument("--query", default="", help="Optional query to run after processing.")
    parser.add_argument("--budget-ms", type=int, default=180000, help="Processing budget for the one-shot idle step.")
    parser.add_argument("--force-idle", action="store_true", help="Force idle processing regardless of activity signal.")
    parser.add_argument(
        "--max-idle-steps",
        type=int,
        default=24,
        help="Maximum number of idle processor steps to run before giving up.",
    )
    parser.add_argument(
        "--synthetic-hid",
        choices=("off", "minimal", "rich"),
        default="minimal",
        help="Inject deterministic synthetic HID metadata/journal records before idle processing.",
    )
    parser.add_argument(
        "--skip-vllm-unstable",
        dest="skip_vllm_unstable",
        action="store_true",
        default=True,
        help="Degrade VLM-dependent processing to skipped when VLM preflight fails (default: true).",
    )
    parser.add_argument(
        "--fail-on-vllm-unstable",
        dest="skip_vllm_unstable",
        action="store_false",
        help="Fail closed when VLM preflight fails.",
    )
    parsed = parser.parse_args(args)

    image_path = Path(str(parsed.image))
    _emit_progress(
        "start",
        image=str(image_path),
        profile=str(parsed.profile),
        budget_ms=int(parsed.budget_ms),
        max_idle_steps=int(parsed.max_idle_steps),
        synthetic_hid=str(parsed.synthetic_hid),
        skip_vllm_unstable=bool(parsed.skip_vllm_unstable),
    )
    if not image_path.exists():
        print(f"ERROR: image not found: {image_path}")
        return 2
    image_bytes = image_path.read_bytes()
    if not image_bytes:
        print("ERROR: image file is empty")
        return 2

    run_dir = resolve_repo_path(parsed.output_dir) / f"single_{_utc_stamp()}"
    config_dir = run_dir / "config"
    data_dir = run_dir / "data"
    report_path = run_dir / "report.json"

    strict_golden = _strict_golden_enabled()
    base_cfg = _load_json(resolve_repo_path(parsed.config_base))
    profile_path = resolve_repo_path(parsed.profile)
    profile_cfg: dict[str, Any] = {}
    if profile_path.exists():
        loaded_profile = _load_json(profile_path)
        if isinstance(loaded_profile, dict):
            profile_cfg = loaded_profile
            base_cfg = _deep_merge_dict(base_cfg, profile_cfg)
    determinism_cfg: dict[str, Any] = {}
    if isinstance(base_cfg.get("plugins"), dict):
        settings = (base_cfg.get("plugins") or {}).get("settings", {})
        if isinstance(settings, dict):
            gp = settings.get("__golden_profile", {})
            if isinstance(gp, dict):
                determinism_cfg = gp.get("determinism", {}) if isinstance(gp.get("determinism"), dict) else {}
    blocked_override_keys = [
        str(x).strip()
        for x in (
            determinism_cfg.get("blocked_env_overrides")
            if isinstance(determinism_cfg.get("blocked_env_overrides"), list)
            else list(STRICT_GOLDEN_ENV_BLOCKLIST)
        )
        if str(x).strip()
    ]
    if strict_golden:
        blocked = _blocked_env_overrides(blocked_override_keys)
        if blocked:
            print(
                f"ERROR: strict_golden_env_override_blocked:{','.join(blocked)}",
                file=sys.stderr,
            )
            return 2
    os.environ.setdefault("AUTOCAPTURE_VLM_BASE_URL", EXTERNAL_VLLM_BASE_URL)
    os.environ.setdefault("AUTOCAPTURE_VLM_MODEL", "internvl3_5_8b")
    os.environ.setdefault("AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S", "45")
    os.environ.setdefault("AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_MAX_S", "120")
    os.environ.setdefault("AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_SCALE", "1.5")
    os.environ.setdefault("AUTOCAPTURE_VLM_PREFLIGHT_RETRIES", "3")
    os.environ.setdefault("AUTOCAPTURE_VLM_ORCHESTRATOR_WARMUP_S", "20")
    os.environ.setdefault("AUTOCAPTURE_VLM_PREFLIGHT_RETRY_SLEEP_S", "1")
    os.environ.setdefault("AUTOCAPTURE_VLM_MAX_INFLIGHT", "1")
    os.environ.setdefault("AUTOCAPTURE_SST_OCR_MIN_FULL_FRAME_TOKENS", "120")
    os.environ.setdefault("AUTOCAPTURE_SINGLE_IDLE_STEP_MAX_SECONDS", "240")
    os.environ.setdefault(
        "AUTOCAPTURE_VLM_ORCHESTRATOR_CMD",
        "bash /mnt/d/projects/hypervisor/tools/wsl/start_internvl35_8b_with_watch.sh",
    )
    remote_vlm_base_url = EXTERNAL_VLLM_BASE_URL
    remote_vlm_only = True
    # Hard policy invariants for safety.
    base_cfg.setdefault("storage", {})
    if isinstance(base_cfg["storage"], dict):
        base_cfg["storage"]["data_dir"] = str(data_dir)
        base_cfg["storage"]["no_deletion_mode"] = True
        base_cfg["storage"]["raw_first_local"] = True
        # Keep the storage_sqlcipher plugin but run it in plaintext mode so we can
        # persist metadata/media on disk without relying on keyring material.
        base_cfg["storage"]["encryption_enabled"] = False
        base_cfg["storage"]["encryption_required"] = False
    base_cfg.setdefault("paths", {})
    if isinstance(base_cfg["paths"], dict):
        # IMPORTANT: apply_path_defaults prefers `paths.*` over env vars. If left
        # as "data"/"config", later query runs will silently drift back to the
        # repo-local `data/` directory. Make these absolute for this run.
        base_cfg["paths"]["config_dir"] = str(config_dir)
        base_cfg["paths"]["data_dir"] = str(data_dir)
    base_cfg.setdefault("web", {})
    if isinstance(base_cfg["web"], dict):
        base_cfg["web"]["allow_remote"] = False
        base_cfg["web"]["bind_host"] = "127.0.0.1"
    base_cfg.setdefault("runtime", {})
    if isinstance(base_cfg["runtime"], dict):
        enforce_cfg = base_cfg["runtime"].setdefault("mode_enforcement", {})
        if isinstance(enforce_cfg, dict) and bool(parsed.force_idle):
            enforce_cfg["fixture_override"] = True
            enforce_cfg["fixture_override_reason"] = "process_single_screenshot_force_idle"
    base_cfg.setdefault("processing", {})
    if isinstance(base_cfg["processing"], dict):
        idle_cfg = base_cfg["processing"].setdefault("idle", {})
        if isinstance(idle_cfg, dict):
            extractors_cfg = idle_cfg.setdefault("extractors", {})
            if isinstance(extractors_cfg, dict):
                # Ensure both lightweight derived extractors run for single-image
                # debug/eval passes; otherwise VLM can be silently disabled by base config.
                extractors_cfg["ocr"] = True
                extractors_cfg["vlm"] = True
    base_cfg.setdefault("kernel", {})
    if isinstance(base_cfg["kernel"], dict):
        rng_cfg = base_cfg["kernel"].setdefault("rng", {})
        if isinstance(rng_cfg, dict):
            # Some local model stacks call SystemRandom internally.
            rng_cfg["strict"] = False

    # Ensure the run_id is stable and present for prefixed ids.
    run_id = ensure_run_id(base_cfg)
    ts_utc = datetime.now(timezone.utc).isoformat()
    record_id = prefixed_id(run_id, "evidence.capture.frame", 0)

    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Ensure the plaintext storage path is used (SQLCipher plugin in plaintext mode).
    plugins_cfg = base_cfg.setdefault("plugins", {})
    if isinstance(plugins_cfg, dict):
        allowlist = plugins_cfg.setdefault("allowlist", [])
        if isinstance(allowlist, list):
            required_from_profile: list[str] = []
            settings_cfg = plugins_cfg.get("settings", {})
            if isinstance(settings_cfg, dict):
                golden_profile_cfg = settings_cfg.get("__golden_profile", {})
                if isinstance(golden_profile_cfg, dict):
                    raw_required = golden_profile_cfg.get("required_plugins", [])
                    if isinstance(raw_required, list):
                        required_from_profile = [str(x).strip() for x in raw_required if str(x).strip()]
            if "builtin.vlm.vllm_localhost" not in allowlist:
                allowlist.append("builtin.vlm.vllm_localhost")
            if "builtin.vlm.qwen2_vl_2b" not in allowlist:
                allowlist.append("builtin.vlm.qwen2_vl_2b")
            if "builtin.processing.sst.ui_vlm" not in allowlist:
                allowlist.append("builtin.processing.sst.ui_vlm")
            if "builtin.sst.ui.parse" not in allowlist:
                allowlist.append("builtin.sst.ui.parse")
            if "builtin.answer.synth_vllm_localhost" not in allowlist:
                allowlist.append("builtin.answer.synth_vllm_localhost")
            _ensure_core_writer_plugins(allowlist=allowlist)
            # Ensure required-gate plugins are not accidentally filtered out by
            # profile overlays with a narrow allowlist.
            for plugin_id in required_from_profile:
                if plugin_id not in allowlist:
                    allowlist.append(plugin_id)
        permissions_cfg = plugins_cfg.setdefault("permissions", {})
        if isinstance(permissions_cfg, dict):
            localhost_ids = permissions_cfg.setdefault("localhost_allowed_plugin_ids", [])
            if isinstance(localhost_ids, list) and "builtin.vlm.vllm_localhost" not in localhost_ids:
                localhost_ids.append("builtin.vlm.vllm_localhost")
        enabled = plugins_cfg.setdefault("enabled", {})
        if isinstance(enabled, dict):
            enabled["builtin.storage.sqlcipher"] = True
            enabled["builtin.storage.encrypted"] = False
            # Keep tactical QA plugin disabled; query answers should be produced
            # from the general observation graph + retrieval pipeline.
            enabled["builtin.sst.qa.answers"] = False
            enabled["builtin.observation.graph"] = True
            enabled["builtin.processing.sst.ui_vlm"] = True
            enabled["builtin.sst.ui.parse"] = True
            enabled["builtin.answer.synth_vllm_localhost"] = True
            enabled["builtin.vlm.vllm_localhost"] = True
            enabled["builtin.vlm.qwen2_vl_2b"] = not remote_vlm_only
            enabled["builtin.vlm.basic"] = False
            _ensure_core_writer_plugins(enabled=enabled)
        settings = plugins_cfg.setdefault("settings", {})
        if isinstance(settings, dict):
            shared_api_key = str(os.environ.get("AUTOCAPTURE_VLM_API_KEY") or "").strip() or _repo_default_vlm_api_key()
            vllm_settings = settings.setdefault("builtin.vlm.vllm_localhost", {})
            if isinstance(vllm_settings, dict):
                timeout_floor_env = str(os.environ.get("AUTOCAPTURE_VLM_TIMEOUT_FLOOR_S") or "").strip()
                try:
                    min_timeout_s = float(timeout_floor_env) if timeout_floor_env else 12.0
                except Exception:
                    min_timeout_s = 12.0
                min_timeout_s = max(4.0, min_timeout_s)
                vllm_settings["base_url"] = remote_vlm_base_url
                env_api_key = str(os.environ.get("AUTOCAPTURE_VLM_API_KEY") or "").strip()
                cfg_api_key = str(vllm_settings.get("api_key") or "").strip()
                if env_api_key:
                    cfg_api_key = env_api_key
                if not cfg_api_key:
                    cfg_api_key = shared_api_key
                if cfg_api_key:
                    vllm_settings["api_key"] = cfg_api_key
                    shared_api_key = cfg_api_key
                model = str(vllm_settings.get("model") or os.environ.get("AUTOCAPTURE_VLM_MODEL") or "").strip()
                if model:
                    vllm_settings["model"] = model
                try:
                    configured_timeout = float(vllm_settings.get("timeout_s") or 0.0)
                except Exception:
                    configured_timeout = 0.0
                vllm_settings["timeout_s"] = max(min_timeout_s, configured_timeout)
                vllm_settings["fail_open_after_errors"] = _coerce_int(vllm_settings.get("fail_open_after_errors"), 2)
                try:
                    cooldown_s = float(vllm_settings.get("failure_cooldown_s") or 45.0)
                except Exception:
                    cooldown_s = 45.0
                vllm_settings["failure_cooldown_s"] = max(5.0, cooldown_s)
                vllm_settings["two_pass_enabled"] = True
                # Option A contract: maximize ingest-time structured metadata
                # quality while keeping deterministic upper bounds.
                vllm_settings["timeout_s"] = min(_coerce_float(vllm_settings.get("timeout_s"), 25.0), 25.0)
                vllm_settings["max_retries"] = min(_coerce_int(vllm_settings.get("max_retries"), 2), 2)
                vllm_settings["thumb_max_px"] = min(_coerce_int(vllm_settings.get("thumb_max_px"), 1536), 1536)
                vllm_settings["max_rois"] = min(_coerce_int(vllm_settings.get("max_rois"), 7), 7)
                vllm_settings["grid_sections"] = min(_coerce_int(vllm_settings.get("grid_sections"), 6), 6)
                vllm_settings["roi_max_side"] = min(_coerce_int(vllm_settings.get("roi_max_side"), 2048), 2048)
                vllm_settings["thumb_max_tokens"] = min(_coerce_int(vllm_settings.get("thumb_max_tokens"), 640), 640)
                vllm_settings["roi_max_tokens"] = min(_coerce_int(vllm_settings.get("roi_max_tokens"), 1024), 1024)
                vllm_settings["max_tokens"] = min(_coerce_int(vllm_settings.get("max_tokens"), 640), 640)
                vllm_settings["factpack_enabled"] = bool(vllm_settings.get("factpack_enabled", True))
                vllm_settings["factpack_max_tokens"] = min(
                    _coerce_int(vllm_settings.get("factpack_max_tokens"), 1280),
                    1280,
                )
                vllm_settings["topic_factpack_enabled"] = True
                vllm_settings["temperature"] = 0.0
                vllm_settings["top_p"] = 1.0
                vllm_settings["n"] = 1
                if "seed" not in vllm_settings:
                    vllm_settings["seed"] = 0
            ocr_vlm_settings = settings.setdefault("builtin.ocr.nemotron_torch", {})
            if isinstance(ocr_vlm_settings, dict):
                ocr_vlm_settings["base_url"] = remote_vlm_base_url
                if shared_api_key and not str(ocr_vlm_settings.get("api_key") or "").strip():
                    ocr_vlm_settings["api_key"] = shared_api_key
            synth_settings = settings.setdefault("builtin.answer.synth_vllm_localhost", {})
            if isinstance(synth_settings, dict):
                synth_settings["base_url"] = remote_vlm_base_url
                if shared_api_key and not str(synth_settings.get("api_key") or "").strip():
                    synth_settings["api_key"] = shared_api_key
            qwen_settings = settings.setdefault("builtin.vlm.qwen2_vl_2b", {})
            if isinstance(qwen_settings, dict):
                qwen_model = str(
                    os.environ.get("AUTOCAPTURE_QWEN_MODEL")
                    or "/mnt/d/autocapture/models/qwen2-vl-2b-instruct"
                ).strip()
                qwen_settings.setdefault("models", {})
                if isinstance(qwen_settings.get("models"), dict):
                    qwen_settings["models"]["vlm_path"] = qwen_model
                    qwen_settings["models"]["max_rois"] = int(
                        os.environ.get("AUTOCAPTURE_QWEN_MAX_ROIS", "5")
                    )
                    qwen_settings["models"]["roi_max_side"] = int(
                        os.environ.get("AUTOCAPTURE_QWEN_ROI_MAX_SIDE", "1280")
                    )
                    qwen_settings["models"]["roi_max_new_tokens"] = int(
                        os.environ.get("AUTOCAPTURE_QWEN_ROI_MAX_NEW_TOKENS", "220")
                    )
                    qwen_settings["models"]["thumb_max_new_tokens"] = int(
                        os.environ.get("AUTOCAPTURE_QWEN_THUMB_MAX_NEW_TOKENS", "220")
                    )
    if isinstance(plugins_cfg, dict):
        caps_cfg = plugins_cfg.setdefault("capabilities", {})
        if isinstance(caps_cfg, dict):
            stage_hooks = caps_cfg.setdefault("processing.stage.hooks", {})
            if isinstance(stage_hooks, dict):
                stage_hooks["fanout"] = True
                stage_hooks["mode"] = "multi"
                stage_hooks["max_providers"] = max(64, int(stage_hooks.get("max_providers", 0) or 0))
            ocr_cap = caps_cfg.setdefault("ocr.engine", {})
            if isinstance(ocr_cap, dict):
                ocr_cap["fanout"] = True
                ocr_cap["mode"] = "multi"
                ocr_cap["max_providers"] = max(2, int(ocr_cap.get("max_providers", 0) or 0))
                preferred_ocr = ["builtin.ocr.nemotron_torch", "builtin.ocr.rapid", "builtin.ocr.basic"]
                existing_ocr = ocr_cap.get("preferred", [])
                if isinstance(existing_ocr, list):
                    ocr_cap["preferred"] = preferred_ocr + [str(x) for x in existing_ocr if str(x) not in preferred_ocr]
            vision = caps_cfg.setdefault("vision.extractor", {})
            if isinstance(vision, dict):
                preferred = vision.setdefault("preferred", [])
                if isinstance(preferred, list):
                    ordered = ["builtin.vlm.vllm_localhost", "builtin.vlm.basic"]
                    if not remote_vlm_only:
                        ordered.insert(1, "builtin.vlm.qwen2_vl_2b")
                    vision["preferred"] = ordered + [str(x) for x in preferred if str(x) not in ordered]
        fs_policies = plugins_cfg.setdefault("filesystem_policies", {})
        if isinstance(fs_policies, dict):
            qwen_fs = fs_policies.setdefault("builtin.vlm.qwen2_vl_2b", {})
            if isinstance(qwen_fs, dict):
                read_paths = qwen_fs.setdefault("read", [])
                if isinstance(read_paths, list):
                    for path in (
                        str(data_dir),
                        "/dev",
                        "/dev/null",
                        "/tmp",
                        "/proc",
                        "/mnt/d/autocapture/models",
                    ):
                        if path not in read_paths:
                            read_paths.append(path)
                readwrite_paths = qwen_fs.setdefault("readwrite", [])
                if isinstance(readwrite_paths, list):
                    for path in (
                        str(data_dir),
                        "/dev",
                        "/dev/null",
                        "/tmp",
                    ):
                        if path not in readwrite_paths:
                            readwrite_paths.append(path)
            jepa_fs = fs_policies.setdefault("builtin.state.jepa.training", {})
            if isinstance(jepa_fs, dict):
                jepa_rw = jepa_fs.setdefault("readwrite", [])
                if isinstance(jepa_rw, list):
                    for path in (
                        str(data_dir),
                        str(data_dir / "state"),
                        str(data_dir / "state" / "models"),
                        str(data_dir / "state" / "models" / "jepa"),
                    ):
                        if path not in jepa_rw:
                            jepa_rw.append(path)
        hosting_cfg = plugins_cfg.setdefault("hosting", {})
        if isinstance(hosting_cfg, dict):
            hosting_cfg["inproc_allow_all"] = True
            hosting_cfg["inproc_allowlist"] = []

    processing_cfg = base_cfg.setdefault("processing", {})
    if isinstance(processing_cfg, dict):
        idle_cfg = processing_cfg.setdefault("idle", {})
        if isinstance(idle_cfg, dict):
            max_step_seconds = _resolve_idle_step_max_seconds(budget_ms=int(parsed.budget_ms))
            idle_cfg["max_seconds_per_run"] = int(max_step_seconds)
            idle_cfg["max_concurrency_gpu"] = int(idle_cfg.get("max_concurrency_gpu", 1) or 1)
            extractors_cfg = idle_cfg.setdefault("extractors", {})
            if isinstance(extractors_cfg, dict):
                # Strict golden single-image mode should use SST as the single
                # metadata path. Direct idle OCR/VLM extractors duplicate work
                # and can consume most of the per-step budget before SST runs.
                extractors_cfg["ocr"] = False
                extractors_cfg["vlm"] = False
        sst_cfg = processing_cfg.setdefault("sst", {})
        if isinstance(sst_cfg, dict):
            sst_cfg["enabled"] = True
            # Option A contract: metadata quality must come from ingest-time
            # extraction, not query-time image calls.
            sst_cfg["allow_ocr"] = True
            sst_cfg["allow_vlm"] = True
            ui_parse_cfg = sst_cfg.setdefault("ui_parse", {})
            if isinstance(ui_parse_cfg, dict):
                ui_parse_cfg["enabled"] = True
                ui_parse_cfg["mode"] = "vlm_json"
                ui_parse_cfg["fallback_detector"] = False
                default_ui_parse_max = 1 if remote_vlm_only else 2
                ui_parse_cfg["max_providers"] = max(default_ui_parse_max, int(ui_parse_cfg.get("max_providers", 1) or 1))
            ui_vlm_cfg = sst_cfg.setdefault("ui_vlm", {})
            if isinstance(ui_vlm_cfg, dict):
                ui_vlm_cfg["enabled"] = True
                default_ui_vlm_max = 1 if remote_vlm_only else 2
                ui_vlm_cfg["max_providers"] = max(default_ui_vlm_max, int(ui_vlm_cfg.get("max_providers", 1) or 1))

    _write_json(config_dir / "user.json", base_cfg)

    # Boot kernel using this run's config + datadir.
    original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
    original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
    original_hosting_mode = os.environ.get("AUTOCAPTURE_PLUGINS_HOSTING_MODE")
    original_tz = os.environ.get("TZ")
    original_lang = os.environ.get("LANG")
    original_lc_all = os.environ.get("LC_ALL")
    original_pythonhashseed = os.environ.get("PYTHONHASHSEED")
    os.environ["AUTOCAPTURE_CONFIG_DIR"] = str(config_dir)
    os.environ["AUTOCAPTURE_DATA_DIR"] = str(data_dir)

    report: dict[str, Any] = {
        "run_dir": str(run_dir),
        "config_dir": str(config_dir),
        "data_dir": str(data_dir),
        "run_id": run_id,
        "record_id": record_id,
        "image_path": str(image_path),
        "started_utc": ts_utc,
        "force_idle": bool(parsed.force_idle),
        "profile_path": str(profile_path),
        "strict_golden": bool(strict_golden),
    }
    if profile_path.exists():
        report["profile_sha256"] = hashlib.sha256(profile_path.read_bytes()).hexdigest()
    report["determinism_contract"] = {
        "lang": str(determinism_cfg.get("lang") or "C.UTF-8"),
        "timezone": str(determinism_cfg.get("timezone") or "UTC"),
        "pythonhashseed": str(determinism_cfg.get("pythonhashseed") or "0"),
        "blocked_env_overrides": blocked_override_keys,
        "repro_runs": int(determinism_cfg.get("repro_runs") or 3),
    }

    kernel = None
    exit_code = 0
    termination_meta: dict[str, int | None] = {"signal": None}
    prior_signal_handlers: dict[int, Any] = {}

    def _termination_handler(sig_num: int, _frame: Any) -> None:
        termination_meta["signal"] = int(sig_num)
        raise RuntimeError(f"terminated_signal:{int(sig_num)}")

    for sig_name in ("SIGTERM", "SIGINT"):
        sig_obj = getattr(signal, sig_name, None)
        if sig_obj is None:
            continue
        try:
            prior_signal_handlers[int(sig_obj)] = signal.getsignal(sig_obj)
            signal.signal(sig_obj, _termination_handler)
        except Exception:
            continue

    try:
        _emit_progress("kernel.boot.begin", data_dir=str(data_dir), config_dir=str(config_dir))
        os.environ["TZ"] = str(report["determinism_contract"]["timezone"])
        os.environ["LANG"] = str(report["determinism_contract"]["lang"])
        os.environ["LC_ALL"] = str(report["determinism_contract"]["lang"])
        os.environ["PYTHONHASHSEED"] = str(report["determinism_contract"]["pythonhashseed"])
        kernel = Kernel(default_config_paths(), safe_mode=False)
        system = kernel.boot(start_conductor=False, fast_boot=False)
        _emit_progress("kernel.boot.done")
        report["boot_ok"] = True

        metadata = system.get("storage.metadata")
        media = system.get("storage.media")
        journal = system.get("journal.writer") if getattr(system, "has", lambda _n: False)("journal.writer") else None
        report["stores"] = {"metadata": type(metadata).__name__, "media": type(media).__name__}
        report["caps_present"] = {
            "ocr.engine": bool(getattr(system, "has", lambda _n: False)("ocr.engine")),
            "vision.extractor": bool(getattr(system, "has", lambda _n: False)("vision.extractor")),
            "processing.pipeline": bool(getattr(system, "has", lambda _n: False)("processing.pipeline")),
            "storage.metadata": bool(getattr(system, "has", lambda _n: False)("storage.metadata")),
            "storage.media": bool(getattr(system, "has", lambda _n: False)("storage.media")),
        }
        try:
            load_report = collect_plugin_load_report(system)
            report["plugins"] = {"load_report": load_report}
        except Exception:
            load_report = {}
            report["plugins"] = {"load_report": {}}
        golden_cfg = {}
        if isinstance(base_cfg, dict) and isinstance(base_cfg.get("plugins"), dict):
            plugin_settings = (base_cfg.get("plugins") or {}).get("settings", {})
            if isinstance(plugin_settings, dict):
                explicit = plugin_settings.get("__golden_profile", {})
                if isinstance(explicit, dict):
                    golden_cfg = explicit
        if not golden_cfg and isinstance(base_cfg, dict) and isinstance(base_cfg.get("runtime"), dict):
            # Back-compat fallback for older profile overlays.
            runtime_cfg = base_cfg.get("runtime") or {}
            if isinstance(runtime_cfg, dict):
                legacy = runtime_cfg.get("golden_qh")
                if isinstance(legacy, dict):
                    golden_cfg = legacy
        required_plugins = []
        if isinstance(golden_cfg, dict):
            raw_required = golden_cfg.get("required_plugins", [])
            if isinstance(raw_required, list):
                required_plugins = [str(x).strip() for x in raw_required if str(x).strip()]
            profile_id = str(golden_cfg.get("profile_id") or "").strip()
            if profile_id:
                report["profile_id"] = profile_id
        gate_status = _plugin_gate_status(load_report if isinstance(load_report, dict) else {}, required_plugins)
        report["plugins"]["required_gate"] = gate_status
        gate_disabled = str(os.environ.get("AUTOCAPTURE_DISABLE_REQUIRED_PLUGIN_GATE") or "").strip().casefold() in {
            "1",
            "true",
            "yes",
        }
        if required_plugins and not gate_status.get("ok", False) and not gate_disabled:
            missing = ", ".join(gate_status.get("missing_required", []))
            failed = ", ".join(gate_status.get("failed_required", []))
            raise RuntimeError(
                f"required_plugin_gate_failed: missing=[{missing}] failed=[{failed}]"
            )
        vlm_degraded = False
        vlm_degraded_reason = ""
        if _should_require_vlm(required_plugins):
            _emit_progress("vlm.preflight.begin", base_url=EXTERNAL_VLLM_BASE_URL)
            plugin_settings = (base_cfg.get("plugins") or {}).get("settings", {}) if isinstance(base_cfg, dict) else {}
            vllm_cfg = plugin_settings.get("builtin.vlm.vllm_localhost", {}) if isinstance(plugin_settings, dict) else {}
            if not str(os.environ.get("AUTOCAPTURE_VLM_API_KEY") or "").strip():
                cfg_key = str(vllm_cfg.get("api_key") or "").strip() if isinstance(vllm_cfg, dict) else ""
                if not cfg_key:
                    cfg_key = _repo_default_vlm_api_key()
                if cfg_key:
                    os.environ["AUTOCAPTURE_VLM_API_KEY"] = cfg_key
            vlm_preflight_t0 = time.monotonic()
            vllm_status = check_external_vllm_ready(require_completion=True)
            _emit_progress(
                "vlm.preflight.done",
                ok=bool(vllm_status.get("ok", False)),
                latency_ms=int((time.monotonic() - vlm_preflight_t0) * 1000),
                selected_model=str(vllm_status.get("selected_model") or ""),
            )
            report["vllm_status"] = vllm_status
            if not bool(vllm_status.get("ok", False)):
                if bool(parsed.skip_vllm_unstable):
                    vlm_degraded = True
                    vlm_degraded_reason = str(vllm_status.get("error") or "external_vllm_unavailable")
                    report["vllm_status"]["degraded_mode"] = True
                    report["vllm_status"]["degraded_reason"] = str(vlm_degraded_reason)
                    _emit_progress("vlm.preflight.degraded", reason=str(vlm_degraded_reason))
                else:
                    raise RuntimeError(f"external_vllm_unavailable:{vllm_status}")
            models = [str(x).strip() for x in (vllm_status.get("models") or []) if str(x).strip()]
            selected_model = str(vllm_cfg.get("model") or "").strip() if isinstance(vllm_cfg, dict) else ""
            if not vlm_degraded:
                selected_model, model_source = _resolve_strict_model_selection(
                    selected_model=selected_model,
                    served_models=models,
                    strict_golden=bool(strict_golden),
                )
                report["vllm_model_selected"] = selected_model
                report["vllm_model_source"] = model_source
                if selected_model and models and selected_model not in models:
                    raise RuntimeError(
                        f"strict_golden_model_not_served:selected={selected_model}:available={','.join(models)}"
                    )
        try:
            ocr_cap = system.get("ocr.engine") if getattr(system, "has", lambda _n: False)("ocr.engine") else None
            vlm_cap = system.get("vision.extractor") if getattr(system, "has", lambda _n: False)("vision.extractor") else None
            report["providers"] = {
                "ocr": [pid for pid, _p in capability_providers(ocr_cap, "ocr.engine")],
                "vlm": [pid for pid, _p in capability_providers(vlm_cap, "vision.extractor")],
            }
        except Exception:
            report["providers"] = {"ocr": [], "vlm": []}

        frame_record = _build_frame_record(run_id=run_id, record_id=record_id, ts_utc=ts_utc, image_bytes=image_bytes)
        _emit_progress(
            "ingest.frame.begin",
            record_id=str(record_id),
            image_bytes=int(len(image_bytes)),
            ts_utc=str(ts_utc),
        )

        # Media first; metadata should only reference an existing blob.
        if hasattr(media, "put_new"):
            try:
                _safe_call(media, "put_new", record_id, image_bytes, ts_utc=ts_utc)
            except Exception:
                _safe_call(media, "put", record_id, image_bytes, ts_utc=ts_utc)
        else:
            _safe_call(media, "put", record_id, image_bytes, ts_utc=ts_utc)

        _metadata_put(metadata, record_id, frame_record)
        report["ingest_ok"] = True
        _emit_progress("ingest.frame.done", record_id=str(record_id))
        if str(parsed.synthetic_hid or "").strip() in {"minimal", "rich"}:
            _emit_progress("ingest.synthetic_hid.begin", mode=str(parsed.synthetic_hid))
            report["synthetic_hid"] = _inject_synthetic_hid(
                metadata=metadata,
                journal=journal,
                run_id=run_id,
                base_ts_utc=ts_utc,
                mode=str(parsed.synthetic_hid),
            )
            _emit_progress(
                "ingest.synthetic_hid.done",
                mode=str(parsed.synthetic_hid),
                event_count=int((report.get("synthetic_hid") or {}).get("event_count", 0) or 0),
            )
        else:
            report["synthetic_hid"] = {"enabled": False, "mode": "off", "metadata_record_ids": [], "journal_events_written": 0}

        need_vlm = _should_require_vlm(required_plugins)
        if vlm_degraded:
            need_vlm = False
        need_sst = (
            "builtin.processing.sst.pipeline" in required_plugins
            or "builtin.processing.sst.ui_vlm" in required_plugins
        )
        if vlm_degraded:
            need_sst = False
        need_state = any(str(plugin_id).startswith("builtin.state.") for plugin_id in required_plugins)
        idle = IdleProcessor(system)
        if vlm_degraded:
            _disable_vlm_idle_runtime(idle)
            report["vlm_degraded"] = True
            report["vlm_degraded_reason"] = str(vlm_degraded_reason)
        max_steps = max(1, int(parsed.max_idle_steps))
        done = False
        last_stats: dict[str, Any] = {}
        cumulative_stats: dict[str, int] = {}
        per_step_stats: list[dict[str, Any]] = []
        steps_taken = 0
        _emit_progress(
            "idle.loop.begin",
            max_steps=int(max_steps),
            need_vlm=bool(need_vlm),
            need_sst=bool(need_sst),
            need_state=bool(need_state),
        )
        for step_idx in range(max_steps):
            step_t0 = time.monotonic()
            step_done, stats = idle.process_step(
                should_abort=None,
                budget_ms=max(0, int(parsed.budget_ms)),
                persist_checkpoint=False,
            )
            steps_taken = step_idx + 1
            last_stats = asdict(stats) if hasattr(stats, "__dataclass_fields__") else dict(stats)
            per_step_stats.append({"step": int(steps_taken), "stats": dict(last_stats)})
            for key, value in last_stats.items():
                try:
                    cumulative_stats[key] = int(cumulative_stats.get(key, 0)) + int(value or 0)
                except Exception:
                    continue
            done = bool(step_done)
            _emit_progress(
                "idle.step",
                step=int(steps_taken),
                step_done=bool(step_done),
                latency_ms=int((time.monotonic() - step_t0) * 1000),
                stats=last_stats,
            )
            # Stop once the processor declares done, or when state-layer has run.
            # Do not exit solely on sst_runs>0; that can leave state spans unbuilt.
            if _should_stop_idle_loop(
                done=done,
                stats=cumulative_stats,
                need_vlm=need_vlm,
                need_sst=need_sst,
                need_state=need_state,
            ):
                break
        _emit_progress(
            "idle.loop.done",
            steps_taken=int(steps_taken),
            done=bool(done),
            stats_cumulative=cumulative_stats,
        )
        report["idle"] = {
            "done": bool(done),
            "steps_taken": int(steps_taken),
            "max_steps": int(max_steps),
            "stats": last_stats,
            "stats_cumulative": cumulative_stats,
            "step_stats": per_step_stats,
            "budget_ms": int(parsed.budget_ms),
            "required_stats": {
                "need_vlm": bool(need_vlm),
                "need_sst": bool(need_sst),
                "need_state": bool(need_state),
                "vlm_ok": bool(int(cumulative_stats.get("vlm_ok", 0) or 0) > 0),
                "sst_ok": bool(int(cumulative_stats.get("sst_runs", 0) or 0) > 0),
                "state_ok": bool(int(cumulative_stats.get("state_runs", 0) or 0) > 0),
            },
        }

        if parsed.query:
            _emit_progress("query.begin", query=str(parsed.query))
            # Full query path (PromptOps + citations policy + retrieval) against the
            # persisted extracted metadata produced above.
            q = str(parsed.query)
            # Store both query paths so we can debug JEPA/state retrieval separately
            # from the classic retrieval path.
            report["query_basic"] = run_query_without_state(system, q, schedule_extract=False)
            report["query_state"] = run_state_query(system, q)
            report["query_arbitrated"] = run_query(system, q, schedule_extract=False)
            _emit_progress("query.done")
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        _emit_progress("error", error=str(report["error"]))
        exit_code = 1
    finally:
        for sig_num, handler in prior_signal_handlers.items():
            try:
                signal.signal(sig_num, handler)
            except Exception:
                continue
        if kernel is not None and termination_meta.get("signal") is None:
            try:
                kernel.shutdown()
            except Exception:
                pass
        if original_config is not None:
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = original_config
        else:
            os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
        if original_data is not None:
            os.environ["AUTOCAPTURE_DATA_DIR"] = original_data
        else:
            os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
        if original_hosting_mode is not None:
            os.environ["AUTOCAPTURE_PLUGINS_HOSTING_MODE"] = original_hosting_mode
        else:
            os.environ.pop("AUTOCAPTURE_PLUGINS_HOSTING_MODE", None)
        if original_tz is not None:
            os.environ["TZ"] = original_tz
        else:
            os.environ.pop("TZ", None)
        if original_lang is not None:
            os.environ["LANG"] = original_lang
        else:
            os.environ.pop("LANG", None)
        if original_lc_all is not None:
            os.environ["LC_ALL"] = original_lc_all
        else:
            os.environ.pop("LC_ALL", None)
        if original_pythonhashseed is not None:
            os.environ["PYTHONHASHSEED"] = original_pythonhashseed
        else:
            os.environ.pop("PYTHONHASHSEED", None)
        _best_effort_finalize_run_state(
            data_dir,
            error=str(report.get("error") or ""),
            terminated_signal=termination_meta.get("signal"),
        )

    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    _write_json(report_path, report)
    if exit_code != 0:
        _emit_progress("finish", ok=False, report=str(report_path))
        print(json.dumps({"ok": False, "error": report.get("error") or "run_failed", "report": str(report_path)}, sort_keys=True))
        return int(exit_code)
    _emit_progress("finish", ok=True, report=str(report_path))
    print(json.dumps({"ok": True, "report": str(report_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
