"""Validate tools/model_manifest.json for required fields and uniqueness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _error(msg: str, errors: list[str]) -> None:
    errors.append(msg)


def validate_manifest(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["manifest must be a JSON object"]
    if "schema_version" not in payload:
        _error("missing schema_version", errors)
    root_dir = payload.get("root_dir")
    if not isinstance(root_dir, str) or not root_dir.strip():
        _error("root_dir must be a non-empty string", errors)

    hf = payload.get("huggingface", {})
    if not isinstance(hf, dict):
        _error("huggingface must be an object", errors)
        hf = {}
    models = hf.get("models", [])
    if not isinstance(models, list):
        _error("huggingface.models must be a list", errors)
        models = []

    ids: set[str] = set()
    provider_ids: set[str] = set()
    for idx, model in enumerate(models):
        if not isinstance(model, dict):
            _error(f"models[{idx}] must be an object", errors)
            continue
        mid = str(model.get("id", "")).strip()
        if not mid:
            _error(f"models[{idx}] missing id", errors)
        else:
            if mid in ids:
                _error(f"duplicate model id: {mid}", errors)
            ids.add(mid)
        kind = str(model.get("kind", "")).strip()
        if kind not in {"ocr", "vlm", "llm", "embedding"}:
            _error(f"models[{idx}] invalid kind: {kind}", errors)
        subdir = str(model.get("subdir", "")).strip()
        if not subdir:
            _error(f"models[{idx}] missing subdir", errors)
        provider_id = str(model.get("provider_id", "")).strip()
        if kind in {"ocr", "vlm"}:
            if not provider_id:
                _error(f"models[{idx}] missing provider_id for kind={kind}", errors)
            else:
                if provider_id in provider_ids:
                    _error(f"duplicate provider_id: {provider_id}", errors)
                provider_ids.add(provider_id)
        if kind == "ocr":
            files = model.get("files", {})
            if not isinstance(files, dict):
                _error(f"models[{idx}] missing files for ocr model", errors)
            else:
                for key in ("det", "rec", "cls"):
                    val = str(files.get(key, "")).strip()
                    if not val:
                        _error(f"models[{idx}] missing files.{key}", errors)

    vllm = payload.get("vllm")
    if vllm is not None:
        if not isinstance(vllm, dict):
            _error("vllm must be an object", errors)
            vllm = {}
        server = vllm.get("server", {})
        if not isinstance(server, dict):
            _error("vllm.server must be an object", errors)
            server = {}
        host = str(server.get("host", "")).strip()
        if host and host != "127.0.0.1":
            _error("vllm.server.host must be 127.0.0.1", errors)
        if not host:
            _error("vllm.server.host must be set", errors)
        port = server.get("port")
        if not isinstance(port, int) or port <= 0:
            _error("vllm.server.port must be a positive integer", errors)
        api_key = server.get("api_key")
        if api_key is not None and not isinstance(api_key, str):
            _error("vllm.server.api_key must be a string", errors)
        vllm_models = vllm.get("models", [])
        if not isinstance(vllm_models, list):
            _error("vllm.models must be a list", errors)
            vllm_models = []
        vllm_ids: set[str] = set()
        for idx, model in enumerate(vllm_models):
            if not isinstance(model, dict):
                _error(f"vllm.models[{idx}] must be an object", errors)
                continue
            mid = str(model.get("id", "")).strip()
            if not mid:
                _error(f"vllm.models[{idx}] missing id", errors)
            else:
                if mid in vllm_ids:
                    _error(f"duplicate vllm model id: {mid}", errors)
                vllm_ids.add(mid)
            served_id = model.get("served_id")
            if served_id is not None and not isinstance(served_id, str):
                _error(f"vllm.models[{idx}].served_id must be a string", errors)
            kind = str(model.get("kind", "")).strip()
            if kind and kind not in {"llm", "vlm", "embedding"}:
                _error(f"vllm.models[{idx}] invalid kind: {kind}", errors)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="tools/model_manifest.json")
    args = parser.parse_args(argv)
    path = Path(args.path)
    if not path.exists():
        print(f"ERROR: manifest not found: {path}")
        return 2
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_manifest(payload)
    if errors:
        print("ERROR: manifest validation failed")
        for err in errors:
            print(f"- {err}")
        return 2
    print("OK: manifest validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
