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
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.hashing import sha256_canonical
from autocapture_nx.kernel.ids import ensure_run_id, prefixed_id
from autocapture_nx.kernel.loader import Kernel, default_config_paths
from autocapture_nx.kernel.paths import resolve_repo_path
from dataclasses import asdict

from autocapture_nx.kernel.providers import capability_providers
from autocapture_nx.kernel.query import run_query_without_state, run_state_query
from autocapture_nx.processing.idle import IdleProcessor
from autocapture_nx.ux.fixture import collect_plugin_load_report


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


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


def _safe_call(obj: Any, name: str, *args, **kwargs) -> Any:
    fn = getattr(obj, name, None)
    if fn is None or not callable(fn):
        raise RuntimeError(f"{type(obj).__name__} missing callable {name}()")
    return fn(*args, **kwargs)


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, help="Path to a PNG/JPG screenshot on disk.")
    parser.add_argument("--output-dir", default="artifacts/single_image_runs", help="Directory to write run artifacts.")
    parser.add_argument("--config-base", default="config/default.json", help="Base config JSON to load.")
    parser.add_argument("--query", default="", help="Optional query to run after processing.")
    parser.add_argument("--budget-ms", type=int, default=20000, help="Processing budget for the one-shot idle step.")
    parser.add_argument("--force-idle", action="store_true", help="Force idle processing regardless of activity signal.")
    parsed = parser.parse_args(args)

    image_path = Path(str(parsed.image))
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

    base_cfg = _load_json(resolve_repo_path(parsed.config_base))
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

    # Ensure the run_id is stable and present for prefixed ids.
    run_id = ensure_run_id(base_cfg)
    ts_utc = datetime.now(timezone.utc).isoformat()
    record_id = prefixed_id(run_id, "evidence.capture.frame", 0)

    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Ensure the plaintext storage path is used (SQLCipher plugin in plaintext mode).
    plugins_cfg = base_cfg.setdefault("plugins", {})
    if isinstance(plugins_cfg, dict):
        enabled = plugins_cfg.setdefault("enabled", {})
        if isinstance(enabled, dict):
            enabled["builtin.storage.sqlcipher"] = True
            enabled["builtin.storage.encrypted"] = False

    _write_json(config_dir / "user.json", base_cfg)

    # Boot kernel using this run's config + datadir.
    original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
    original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
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
    }

    kernel = None
    try:
        kernel = Kernel(default_config_paths(), safe_mode=False)
        system = kernel.boot(start_conductor=False, fast_boot=False)
        report["boot_ok"] = True

        metadata = system.get("storage.metadata")
        media = system.get("storage.media")
        report["stores"] = {"metadata": type(metadata).__name__, "media": type(media).__name__}
        report["caps_present"] = {
            "ocr.engine": bool(getattr(system, "has", lambda _n: False)("ocr.engine")),
            "vision.extractor": bool(getattr(system, "has", lambda _n: False)("vision.extractor")),
            "processing.pipeline": bool(getattr(system, "has", lambda _n: False)("processing.pipeline")),
            "storage.metadata": bool(getattr(system, "has", lambda _n: False)("storage.metadata")),
            "storage.media": bool(getattr(system, "has", lambda _n: False)("storage.media")),
        }
        try:
            report["plugins"] = {"load_report": collect_plugin_load_report(system)}
        except Exception:
            report["plugins"] = {"load_report": []}
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

        # Media first; metadata should only reference an existing blob.
        if hasattr(media, "put_new"):
            try:
                _safe_call(media, "put_new", record_id, image_bytes, ts_utc=ts_utc)
            except Exception:
                _safe_call(media, "put", record_id, image_bytes, ts_utc=ts_utc)
        else:
            _safe_call(media, "put", record_id, image_bytes, ts_utc=ts_utc)

        if hasattr(metadata, "put_new"):
            try:
                _safe_call(metadata, "put_new", record_id, frame_record)
            except Exception:
                _safe_call(metadata, "put", record_id, frame_record)
        else:
            _safe_call(metadata, "put", record_id, frame_record)
        report["ingest_ok"] = True

        idle = IdleProcessor(system)
        done, stats = idle.process_step(
            should_abort=None,
            budget_ms=max(0, int(parsed.budget_ms)),
            persist_checkpoint=False,
        )
        report["idle"] = {
            "done": bool(done),
            "stats": asdict(stats) if hasattr(stats, "__dataclass_fields__") else dict(stats),
            "budget_ms": int(parsed.budget_ms),
        }

        if parsed.query:
            # Full query path (PromptOps + citations policy + retrieval) against the
            # persisted extracted metadata produced above.
            q = str(parsed.query)
            # Store both query paths so we can debug JEPA/state retrieval separately
            # from the classic retrieval path.
            report["query_basic"] = run_query_without_state(system, q, schedule_extract=False)
            report["query_state"] = run_state_query(system, q)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        _write_json(report_path, report)
        return 1
    finally:
        if kernel is not None:
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

    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    _write_json(report_path, report)
    print(json.dumps({"ok": True, "report": str(report_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
