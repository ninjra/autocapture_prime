"""External vLLM endpoint policy and probe helpers."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.parse
from typing import Any

from autocapture_nx.runtime.http_localhost import request_json
from autocapture_nx.runtime.service_ports import VLM_BASE_URL, VLM_MODEL_ID, VLM_ROOT_URL

EXTERNAL_VLLM_ROOT_URL = VLM_ROOT_URL
EXTERNAL_VLLM_BASE_URL = VLM_BASE_URL
EXTERNAL_VLLM_EXPECTED_MODEL = VLM_MODEL_ID
EXTERNAL_VLLM_ORCHESTRATOR_CMD = "bash /mnt/d/projects/hypervisor/tools/wsl/start_internvl35_8b_with_watch.sh"
EXTERNAL_VLLM_WATCH_STATE_PATH = "/tmp/hypervisor-thermal-brain/vllm_watch_state.json"
_ALLOWED_SCHEME = "http"
_ALLOWED_HOST = "127.0.0.1"
_ALLOWED_PORTS = {8000}


def enforce_external_vllm_base_url(candidate: str | None) -> str:
    """Return canonical external base URL or raise on policy violation."""
    raw = str(candidate or "").strip()
    if not raw:
        return EXTERNAL_VLLM_BASE_URL
    parsed = urllib.parse.urlparse(raw)
    scheme = str(parsed.scheme or "").strip().lower()
    host = str(parsed.hostname or "").strip()
    port = int(parsed.port or 0)
    if scheme != _ALLOWED_SCHEME:
        raise ValueError(f"invalid_vllm_scheme:{scheme or 'missing'}")
    if host != _ALLOWED_HOST:
        raise ValueError(f"invalid_vllm_host:{host or 'missing'}")
    if port not in _ALLOWED_PORTS:
        raise ValueError(f"invalid_vllm_port:{port}")
    path = str(parsed.path or "").strip().rstrip("/")
    if path not in {"", "/v1"}:
        raise ValueError(f"invalid_vllm_path:{path or '/'}")
    return f"http://{_ALLOWED_HOST}:{port}/v1"


def _env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    try:
        return float(raw) if raw else float(default)
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    try:
        return int(raw) if raw else int(default)
    except Exception:
        return int(default)


def _emit_preflight_progress(stage: str, **fields: Any) -> None:
    enabled = str(os.environ.get("AUTOCAPTURE_VLM_PREFLIGHT_PROGRESS") or "").strip().casefold() in {"1", "true", "yes", "on"}
    if not enabled:
        return
    payload: dict[str, Any] = {
        "event": "vllm_preflight.progress",
        "stage": str(stage),
        "ts_unix_ms": int(round(time.time() * 1000.0)),
    }
    payload.update(fields)
    try:
        print(json.dumps(payload, sort_keys=True), file=sys.stderr, flush=True)
    except Exception:
        return


def _norm_model_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _model_aliases(expected_model: str) -> set[str]:
    base = _norm_model_id(expected_model)
    aliases = {base}
    raw_aliases = str(os.environ.get("AUTOCAPTURE_VLM_MODEL_ALIASES") or "").strip()
    if raw_aliases:
        for item in raw_aliases.split(","):
            norm = _norm_model_id(item)
            if norm:
                aliases.add(norm)
    # Canonical internvl3.5-8b aliases.
    aliases.update(
        {
            _norm_model_id("internvl3_5_8b"),
            _norm_model_id("internvl3.5-8b"),
            _norm_model_id("internvl35_8b"),
            _norm_model_id("internvl3_5_8b_instruct"),
        }
    )
    return {item for item in aliases if item}


def _model_matches_expected(served_model_id: str, expected_aliases: set[str]) -> bool:
    served_norm = _norm_model_id(served_model_id)
    if not served_norm:
        return False
    for alias in expected_aliases:
        if alias and (served_norm == alias or alias in served_norm or served_norm in alias):
            return True
    return False


def _read_watch_state(path: str) -> dict[str, Any] | None:
    p = str(path or "").strip()
    if not p:
        return None
    try:
        with open(p, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return None
    return None


def _invoke_orchestrator_once(cmd: str, *, timeout_s: float) -> dict[str, Any]:
    command = str(cmd or "").strip()
    if not command:
        return {"ok": False, "error": "orchestrator_cmd_missing", "cmd": command}
    t0 = time.perf_counter()
    grace_s = _env_float("AUTOCAPTURE_VLM_ORCHESTRATOR_GRACE_S", 3.0)
    grace_s = max(0.5, min(float(timeout_s), grace_s))
    try:
        proc = subprocess.Popen(
            shlex.split(command),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=False,
        )
        try:
            rc = proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            # Long-running watcher/supervisor start command: treat as accepted
            # and continue preflight retries against the endpoint.
            return {
                "ok": True,
                "cmd": command,
                "returncode": None,
                "detached": True,
                "pid": int(proc.pid),
                "latency_ms": int(round((time.perf_counter() - t0) * 1000.0)),
            }
        return {
            "ok": bool(rc == 0),
            "cmd": command,
            "returncode": int(rc),
            "detached": False,
            "pid": int(proc.pid),
            "latency_ms": int(round((time.perf_counter() - t0) * 1000.0)),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"orchestrator_exec_failed:{type(exc).__name__}",
            "cmd": command,
            "latency_ms": int(round((time.perf_counter() - t0) * 1000.0)),
        }


def _preflight_once(
    *,
    base_url: str,
    expected_model: str,
    timeout_models_s: float,
    timeout_completion_s: float,
    require_completion: bool,
) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "base_url": str(base_url), "expected_model": str(expected_model)}
    api_key = str(os.environ.get("AUTOCAPTURE_VLM_API_KEY") or "").strip()
    auth_headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    t0 = time.perf_counter()
    models_url = f"{base_url}/models"
    completion_url = f"{base_url}/chat/completions"
    models_out = request_json(
        method="GET",
        url=models_url,
        timeout_s=float(timeout_models_s),
        headers=auth_headers,
    )
    if not bool(models_out.get("ok", False)):
        models_status = int(models_out.get("status", 0) or 0)
        if models_status >= 400:
            out["error"] = f"models_http_{models_status}"
        else:
            m_err = str(models_out.get("error") or "").strip()
            out["error"] = f"models_unreachable:{m_err or 'UnknownError'}"
        out["latency_ms"] = int(round((time.perf_counter() - t0) * 1000.0))
        return out
    payload = models_out.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}
    out["models_status"] = int(models_out.get("status", 0) or 0)

    models: list[str] = []
    data = payload.get("data", []) if isinstance(payload, dict) else []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                model_id = str(item.get("id") or "").strip()
                if model_id:
                    models.append(model_id)
    out["models"] = models
    if not models:
        out["error"] = "models_empty"
        out["latency_ms"] = int(round((time.perf_counter() - t0) * 1000.0))
        return out

    aliases = _model_aliases(expected_model)
    selected = ""
    for mid in models:
        if _model_matches_expected(mid, aliases):
            selected = mid
            break
    if not selected:
        out["error"] = "models_missing_expected"
        out["latency_ms"] = int(round((time.perf_counter() - t0) * 1000.0))
        return out
    out["selected_model"] = selected

    if bool(require_completion):
        completion_out = request_json(
            method="POST",
            url=completion_url,
            timeout_s=float(timeout_completion_s),
            payload={
                "model": selected,
                "messages": [{"role": "user", "content": "ping"}],
                "temperature": 0,
                "max_completion_tokens": 8,
                "max_tokens": 8,
            },
            headers=auth_headers,
        )
        if not bool(completion_out.get("ok", False)):
            completion_status = int(completion_out.get("status", 0) or 0)
            if completion_status >= 400:
                out["error"] = f"completion_http_{completion_status}"
            else:
                c_err = str(completion_out.get("error") or "").strip()
                out["error"] = f"completion_unreachable:{c_err or 'UnknownError'}"
            out["latency_ms"] = int(round((time.perf_counter() - t0) * 1000.0))
            return out
        completion_payload = completion_out.get("payload", {})
        if not isinstance(completion_payload, dict):
            completion_payload = {}
        out["completion_status"] = int(completion_out.get("status", 0) or 0)
        choices = completion_payload.get("choices", []) if isinstance(completion_payload, dict) else []
        completion_ok = isinstance(choices, list) and len(choices) > 0
        out["completion_ok"] = bool(completion_ok)
        if not completion_ok:
            out["error"] = "completion_empty"
            out["latency_ms"] = int(round((time.perf_counter() - t0) * 1000.0))
            return out

    out["ok"] = True
    out["latency_ms"] = int(round((time.perf_counter() - t0) * 1000.0))
    return out


def check_external_vllm_ready(
    *,
    timeout_models_s: float | None = None,
    timeout_completion_s: float | None = None,
    require_completion: bool = True,
    retries: int | None = None,
    auto_recover: bool = True,
) -> dict[str, Any]:
    """Probe required external vLLM routes and optionally recover via orchestrator.

    Contract:
    A) GET /v1/models
    B) expected model present (exact or canonical alias)
    C) POST /v1/chat/completions ping
    """
    t0 = time.perf_counter()
    base_raw = str(os.environ.get("AUTOCAPTURE_VLM_BASE_URL") or "").strip()
    expected_model = str(os.environ.get("AUTOCAPTURE_VLM_MODEL") or "").strip() or EXTERNAL_VLLM_EXPECTED_MODEL
    models_timeout = float(timeout_models_s) if timeout_models_s is not None else _env_float("AUTOCAPTURE_VLM_PREFLIGHT_MODELS_TIMEOUT_S", 4.0)
    if models_timeout <= 0:
        models_timeout = _env_float("AUTOCAPTURE_VLM_PREFLIGHT_MODELS_TIMEOUT_S", 4.0)
    preflight_retries = int(retries if retries is not None else _env_int("AUTOCAPTURE_VLM_PREFLIGHT_RETRIES", 3))
    preflight_retries = max(1, preflight_retries)
    completion_timeout = float(timeout_completion_s) if timeout_completion_s is not None else _env_float("AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S", 12.0)
    if completion_timeout <= 0:
        completion_timeout = _env_float("AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S", 12.0)
    completion_timeout_max = _env_float("AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_MAX_S", 60.0)
    completion_timeout_max = max(completion_timeout, completion_timeout_max)
    completion_timeout_scale = _env_float("AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_SCALE", 1.5)
    completion_timeout_scale = max(1.0, completion_timeout_scale)
    total_timeout_s = _env_float("AUTOCAPTURE_VLM_PREFLIGHT_TOTAL_TIMEOUT_S", 180.0)
    total_timeout_s = max(10.0, total_timeout_s)
    orchestrator_cmd = str(os.environ.get("AUTOCAPTURE_VLM_ORCHESTRATOR_CMD") or "").strip() or EXTERNAL_VLLM_ORCHESTRATOR_CMD
    watch_path = str(os.environ.get("AUTOCAPTURE_VLM_WATCH_STATE_PATH") or "").strip() or EXTERNAL_VLLM_WATCH_STATE_PATH
    out: dict[str, Any] = {
        "ok": False,
        "base_url": EXTERNAL_VLLM_BASE_URL,
        "expected_model": expected_model,
        "orchestrator_cmd": orchestrator_cmd,
    }
    try:
        base_url = enforce_external_vllm_base_url(base_raw)
    except Exception as exc:
        out["error"] = f"invalid_base_url:{type(exc).__name__}:{exc}"
        out["latency_ms"] = int(round((time.perf_counter() - t0) * 1000.0))
        return out
    out["base_url"] = base_url
    _emit_preflight_progress(
        "start",
        base_url=base_url,
        expected_model=expected_model,
        require_completion=bool(require_completion),
        timeout_models_s=float(models_timeout),
        timeout_completion_s=float(completion_timeout),
        retries=int(preflight_retries),
        total_timeout_s=float(total_timeout_s),
    )

    first = _preflight_once(
        base_url=base_url,
        expected_model=expected_model,
        timeout_models_s=float(models_timeout),
        timeout_completion_s=float(completion_timeout),
        require_completion=bool(require_completion),
    )
    _emit_preflight_progress("attempt", attempt=1, ok=bool(first.get("ok", False)), error=str(first.get("error") or ""))
    if bool(first.get("ok", False)):
        first["attempts"] = 1
        first["latency_ms"] = int(round((time.perf_counter() - t0) * 1000.0))
        watch_state = _read_watch_state(watch_path)
        if watch_state is not None:
            first["watch_state"] = watch_state
        return first

    out["initial_error"] = str(first.get("error") or "preflight_failed")
    out["initial"] = first
    if not bool(auto_recover):
        out["error"] = str(first.get("error") or "preflight_failed")
        out["attempts"] = 1
        out["latency_ms"] = int(round((time.perf_counter() - t0) * 1000.0))
        watch_state = _read_watch_state(watch_path)
        if watch_state is not None:
            out["watch_state"] = watch_state
        return out

    orchestrator = _invoke_orchestrator_once(orchestrator_cmd, timeout_s=_env_float("AUTOCAPTURE_VLM_ORCHESTRATOR_TIMEOUT_S", 120.0))
    out["orchestrator"] = orchestrator
    _emit_preflight_progress(
        "orchestrator",
        ok=bool(orchestrator.get("ok", False)),
        detached=bool(orchestrator.get("detached", False)),
        returncode=orchestrator.get("returncode"),
    )
    orch_exec_error = str(orchestrator.get("error") or "").strip()
    if orch_exec_error.startswith("orchestrator_exec_failed") or orch_exec_error == "orchestrator_cmd_missing":
        out["error"] = f"orchestrator_failed:{orchestrator.get('error') or orchestrator.get('returncode')}"
        out["attempts"] = 1
        out["latency_ms"] = int(round((time.perf_counter() - t0) * 1000.0))
        watch_state = _read_watch_state(watch_path)
        if watch_state is not None:
            out["watch_state"] = watch_state
        return out

    sleep_s = _env_float("AUTOCAPTURE_VLM_PREFLIGHT_RETRY_SLEEP_S", 1.0)
    warmup_s = _env_float("AUTOCAPTURE_VLM_ORCHESTRATOR_WARMUP_S", 60.0)
    warmup_s = max(0.0, warmup_s)
    poll_s = _env_float("AUTOCAPTURE_VLM_ORCHESTRATOR_POLL_S", max(1.0, sleep_s))
    poll_s = max(0.2, poll_s)
    max_attempts = max(1, preflight_retries)
    last = first
    attempts_done = 1
    timeout_s_current = float(completion_timeout)
    deadline = time.perf_counter() + warmup_s
    while True:
        if (time.perf_counter() - t0) >= float(total_timeout_s):
            break
        if sleep_s > 0:
            time.sleep(sleep_s)
        last_error = str(last.get("error") or "")
        if last_error.startswith("completion_unreachable:TimeoutError"):
            timeout_s_current = min(float(completion_timeout_max), float(timeout_s_current) * float(completion_timeout_scale))
        attempt = _preflight_once(
            base_url=base_url,
            expected_model=expected_model,
            timeout_models_s=float(models_timeout),
            timeout_completion_s=float(timeout_s_current),
            require_completion=bool(require_completion),
        )
        attempts_done += 1
        last = attempt
        _emit_preflight_progress(
            "attempt",
            attempt=int(attempts_done),
            ok=bool(attempt.get("ok", False)),
            error=str(attempt.get("error") or ""),
            timeout_completion_s=float(timeout_s_current),
        )
        if bool(attempt.get("ok", False)):
            attempt["recovered"] = True
            attempt["attempts"] = attempts_done
            attempt["latency_ms"] = int(round((time.perf_counter() - t0) * 1000.0))
            attempt["orchestrator"] = orchestrator
            watch_state = _read_watch_state(watch_path)
            if watch_state is not None:
                attempt["watch_state"] = watch_state
            return attempt
        if attempts_done >= max_attempts + 1 and time.perf_counter() >= deadline:
            break
        sleep_s = poll_s

    out["error"] = str(last.get("error") or "preflight_failed_after_retries")
    if (time.perf_counter() - t0) >= float(total_timeout_s):
        out["error"] = f"preflight_total_timeout:{round(float(total_timeout_s), 3)}s"
    out["attempts"] = int(attempts_done)
    out["latency_ms"] = int(round((time.perf_counter() - t0) * 1000.0))
    out["final"] = last
    watch_state = _read_watch_state(watch_path)
    if watch_state is not None:
        out["watch_state"] = watch_state
    return out
