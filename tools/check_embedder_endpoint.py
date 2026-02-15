#!/usr/bin/env python3
"""Validate OpenAI-compatible embedder endpoint readiness."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8001"
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_config_path(raw: str) -> Path:
    value = str(raw or "").strip()
    if not value:
        env_dir = str(os.environ.get("AUTOCAPTURE_CONFIG_DIR") or "").strip()
        if env_dir:
            return Path(env_dir) / "user.json"
        return Path("config/default.json")
    path = Path(value)
    if path.is_dir():
        return path / "user.json"
    return path


def _resolve_endpoint_settings(config: dict[str, Any]) -> tuple[str, str]:
    plugins = config.get("plugins", {}) if isinstance(config, dict) else {}
    settings = plugins.get("settings", {}) if isinstance(plugins, dict) else {}
    embedder = settings.get("builtin.embedder.vllm_localhost", {}) if isinstance(settings, dict) else {}
    base_url = str(embedder.get("base_url") or "").strip() if isinstance(embedder, dict) else ""
    model = str(embedder.get("model") or "").strip() if isinstance(embedder, dict) else ""
    base_url = str(os.environ.get("AUTOCAPTURE_EMBEDDER_BASE_URL") or base_url or DEFAULT_BASE_URL).strip()
    model = str(os.environ.get("AUTOCAPTURE_EMBEDDER_MODEL") or model or DEFAULT_MODEL).strip()
    return base_url.rstrip("/"), model


def _http_json(
    *,
    method: str,
    url: str,
    timeout_s: float,
    payload: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any], str]:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
    req = urllib.request.Request(url=url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read() or b"{}"
            text = body.decode("utf-8", errors="replace")
            parsed = json.loads(text) if text.strip() else {}
            return True, parsed if isinstance(parsed, dict) else {"raw": parsed}, ""
    except urllib.error.HTTPError as exc:
        detail = f"http_error:{exc.code}"
        try:
            body = exc.read()
            if body:
                detail = f"{detail}:{body.decode('utf-8', errors='replace')[:400]}"
        except Exception:
            pass
        return False, {}, detail
    except Exception as exc:
        return False, {}, f"{type(exc).__name__}:{exc}"


def _probe(base_url: str, model: str, timeout_s: float) -> dict[str, Any]:
    health_ok, health_payload, health_error = _http_json(
        method="GET",
        url=f"{base_url}/health",
        timeout_s=timeout_s,
    )
    models_ok, models_payload, models_error = _http_json(
        method="GET",
        url=f"{base_url}/v1/models",
        timeout_s=timeout_s,
    )
    embeddings_ok, embeddings_payload, embeddings_error = _http_json(
        method="POST",
        url=f"{base_url}/v1/embeddings",
        timeout_s=timeout_s,
        payload={"model": model, "input": ["embedding smoke test"]},
    )
    embedding_dim = 0
    if embeddings_ok:
        data = embeddings_payload.get("data", [])
        if isinstance(data, list) and data:
            first = data[0] if isinstance(data[0], dict) else {}
            emb = first.get("embedding", []) if isinstance(first, dict) else []
            if isinstance(emb, list):
                embedding_dim = len(emb)
    ok = bool(health_ok and models_ok and embeddings_ok and embedding_dim > 0)
    return {
        "ok": ok,
        "base_url": base_url,
        "model": model,
        "checks": {
            "health": {"ok": bool(health_ok), "error": health_error or "", "payload": health_payload},
            "models": {"ok": bool(models_ok), "error": models_error or "", "payload": models_payload},
            "embeddings": {
                "ok": bool(embeddings_ok),
                "error": embeddings_error or "",
                "payload": embeddings_payload,
                "embedding_dim": int(embedding_dim),
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="", help="Path to config file or config dir.")
    parser.add_argument("--base-url", default="", help="Override embedder base URL.")
    parser.add_argument("--model", default="", help="Override embedding model id.")
    parser.add_argument("--timeout-s", type=float, default=3.0, help="HTTP timeout in seconds.")
    parser.add_argument("--require-live", action="store_true", help="Exit non-zero if endpoint is not ready.")
    args = parser.parse_args(argv)

    config_path = _resolve_config_path(args.config)
    config: dict[str, Any] = {}
    if config_path.exists():
        try:
            config = _load_json(config_path)
        except Exception:
            config = {}
    base_url, model = _resolve_endpoint_settings(config)
    if str(args.base_url or "").strip():
        base_url = str(args.base_url).strip().rstrip("/")
    if str(args.model or "").strip():
        model = str(args.model).strip()

    result = _probe(base_url, model, float(args.timeout_s))
    result["config_path"] = str(config_path)
    print(json.dumps(result, sort_keys=True))
    if args.require_live and not bool(result.get("ok", False)):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
