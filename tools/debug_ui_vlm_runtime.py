#!/usr/bin/env python3
"""Debug VLM ui.parse hook behavior for a single run artifact."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.loader import Kernel, default_config_paths
from autocapture_nx.kernel.providers import capability_providers


def _load_latest_state(data_dir: Path) -> tuple[str, int, int, list[dict[str, Any]]]:
    db_path = data_dir / "metadata.db"
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        row = cur.execute(
            "select payload from metadata where record_type=? order by ts_utc desc limit 1",
            ("derived.sst.state",),
        ).fetchone()
        if row is None:
            raise RuntimeError("No derived.sst.state record found.")
        payload = json.loads(str(row[0]))
    finally:
        con.close()
    frame_id = str(payload.get("frame_id") or "")
    screen_state = payload.get("screen_state", {})
    if not frame_id:
        raise RuntimeError("derived.sst.state payload missing frame_id.")
    if not isinstance(screen_state, dict):
        raise RuntimeError("derived.sst.state screen_state missing/invalid.")
    width = int(screen_state.get("width") or 0)
    height = int(screen_state.get("height") or 0)
    tokens = screen_state.get("tokens", [])
    if not isinstance(tokens, list):
        tokens = []
    return frame_id, width, height, tokens


def _frame_bytes(system: Any, frame_id: str) -> bytes:
    media = system.get("storage.media")
    for method in ("get", "read", "read_bytes"):
        fn = getattr(media, method, None)
        if not callable(fn):
            continue
        try:
            value = fn(frame_id)
        except Exception:
            continue
        if isinstance(value, dict):
            maybe = value.get("bytes") or value.get("content") or b""
            value = maybe
        if isinstance(value, str):
            value = value.encode("utf-8")
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
    return b""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()

    config_dir = Path(args.config_dir).resolve()
    data_dir = Path(args.data_dir).resolve()
    if not config_dir.exists():
        raise SystemExit(f"missing config dir: {config_dir}")
    if not data_dir.exists():
        raise SystemExit(f"missing data dir: {data_dir}")

    frame_id, width, height, tokens = _load_latest_state(data_dir)
    print(f"frame_id={frame_id}")
    print(f"frame_size={width}x{height}")
    print(f"tokens={len(tokens)}")

    import os

    old_cfg = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
    old_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
    os.environ["AUTOCAPTURE_CONFIG_DIR"] = str(config_dir)
    os.environ["AUTOCAPTURE_DATA_DIR"] = str(data_dir)

    kernel = Kernel(default_config_paths(), safe_mode=False)
    try:
        system = kernel.boot(start_conductor=False, fast_boot=False)
        frame = _frame_bytes(system, frame_id)
        print(f"frame_bytes={len(frame)}")

        vlm_cap = system.get("vision.extractor") if system.has("vision.extractor") else None
        vlm_providers = capability_providers(vlm_cap, "vision.extractor")
        print("vision.extractor providers:", [pid for pid, _ in vlm_providers])
        for provider_id, provider in vlm_providers:
            try:
                response = provider.extract(frame)
            except Exception as exc:
                print(f"[{provider_id}] extract error: {type(exc).__name__}: {exc}")
                continue
            if not isinstance(response, dict):
                print(f"[{provider_id}] non-dict response type={type(response).__name__}")
                continue
            layout = response.get("layout") if isinstance(response.get("layout"), dict) else {}
            elements = layout.get("elements", []) if isinstance(layout.get("elements", []), list) else []
            text = str(response.get("text") or response.get("text_plain") or response.get("caption") or "")
            print(
                f"[{provider_id}] backend={response.get('backend')} layout_elements={len(elements)} "
                f"text_len={len(text)} keys={sorted(response.keys())}"
            )
            model_error = str(response.get("model_error") or "").strip()
            if model_error:
                print(f"[{provider_id}] model_error={model_error}")
            if text:
                head = text[:220].replace("\n", " ")
                print(f"[{provider_id}] text_head={head}")

        hooks_cap = system.get("processing.stage.hooks") if system.has("processing.stage.hooks") else None
        hook_providers = capability_providers(hooks_cap, "processing.stage.hooks")
        print("processing.stage.hooks providers:", [pid for pid, _ in hook_providers])
        for provider_id, provider in hook_providers:
            if provider_id != "builtin.processing.sst.ui_vlm":
                continue
            try:
                result = provider.run_stage(
                    "ui.parse",
                    {
                        "frame_bytes": frame,
                        "frame_bbox": (0, 0, width, height),
                        "tokens": tokens,
                    },
                )
            except Exception as exc:
                print(f"[{provider_id}] run_stage error: {type(exc).__name__}: {exc}")
                continue
            print(f"[{provider_id}] run_stage returned None? {result is None}")
            if isinstance(result, dict):
                graph = result.get("element_graph", {}) if isinstance(result.get("element_graph"), dict) else {}
                print(
                    f"[{provider_id}] graph state_id={graph.get('state_id')} "
                    f"source_state_id={graph.get('source_state_id')} "
                    f"backend={graph.get('source_backend')} "
                    f"provider={graph.get('source_provider_id')} "
                    f"elements={len(graph.get('elements', []))}"
                )
    finally:
        kernel.shutdown()
        if old_cfg is not None:
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = old_cfg
        else:
            os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
        if old_data is not None:
            os.environ["AUTOCAPTURE_DATA_DIR"] = old_data
        else:
            os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
