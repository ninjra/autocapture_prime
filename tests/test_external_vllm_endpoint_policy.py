from __future__ import annotations

from pathlib import Path
import json
import subprocess
import urllib.error

import pytest

from autocapture_nx.inference.vllm_endpoint import (
    EXTERNAL_VLLM_BASE_URL,
    check_external_vllm_ready,
    enforce_external_vllm_base_url,
)


def test_enforce_external_vllm_base_url_accepts_default_and_canonical() -> None:
    assert enforce_external_vllm_base_url(None) == EXTERNAL_VLLM_BASE_URL
    assert enforce_external_vllm_base_url("") == EXTERNAL_VLLM_BASE_URL
    assert enforce_external_vllm_base_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000/v1"


@pytest.mark.parametrize(
    "candidate",
    [
        "http://localhost:8000",
        "http://127.0.0.1:9000",
        "http://127.0.0.1:8001",
        "http://127.0.0.1:34221",
        "https://127.0.0.1:8000",
        "http://0.0.0.0:8000",
        "http://192.168.1.10:8000",
    ],
)
def test_enforce_external_vllm_base_url_rejects_noncanonical(candidate: str) -> None:
    with pytest.raises(ValueError):
        enforce_external_vllm_base_url(candidate)


def test_vllm_plugins_apply_external_endpoint_policy() -> None:
    files = (
        "plugins/builtin/vlm_vllm_localhost/plugin.py",
        "plugins/builtin/answer_synth_vllm_localhost/plugin.py",
        "plugins/builtin/embedder_vllm_localhost/plugin.py",
        "plugins/builtin/ocr_nemotron_torch/plugin.py",
    )
    for rel in files:
        text = Path(rel).read_text(encoding="utf-8")
        assert "enforce_external_vllm_base_url" in text


def test_check_external_vllm_ready_with_completion_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        def __init__(self, status: int, payload: dict | None = None) -> None:
            self.status = status
            self._payload = payload or {}

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

    def _urlopen(req, timeout=0):  # noqa: ARG001
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url.endswith("/v1/models"):
            return _Resp(200, {"data": [{"id": "internvl3_5_8b"}]})
        if url.endswith("/v1/chat/completions"):
            return _Resp(200, {"choices": [{"message": {"content": "pong"}}]})
        raise AssertionError(url)

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    out = check_external_vllm_ready(require_completion=True)
    assert out["ok"] is True
    assert out["completion_ok"] is True
    assert out["models"] == ["internvl3_5_8b"]
    assert out["selected_model"] == "internvl3_5_8b"


def test_check_external_vllm_ready_missing_expected_model_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        def __init__(self, status: int, payload: dict | None = None) -> None:
            self.status = status
            self._payload = payload or {}

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

    def _urlopen(req, timeout=0):  # noqa: ARG001
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url.endswith("/v1/models"):
            return _Resp(200, {"data": [{"id": "some_other_model"}]})
        raise AssertionError(url)

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    out = check_external_vllm_ready(require_completion=True, auto_recover=False)
    assert out["ok"] is False
    assert out["error"] == "models_missing_expected"


def test_check_external_vllm_ready_completion_empty_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        def __init__(self, status: int, payload: dict | None = None) -> None:
            self.status = status
            self._payload = payload or {}

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

    def _urlopen(req, timeout=0):  # noqa: ARG001
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url.endswith("/v1/models"):
            return _Resp(200, {"data": [{"id": "internvl3_5_8b"}]})
        if url.endswith("/v1/chat/completions"):
            return _Resp(200, {"choices": []})
        raise AssertionError(url)

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    out = check_external_vllm_ready(require_completion=True, auto_recover=False)
    assert out["ok"] is False
    assert out["error"] == "completion_empty"


def test_check_external_vllm_ready_invokes_orchestrator_once_then_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        def __init__(self, status: int, payload: dict | None = None) -> None:
            self.status = status
            self._payload = payload or {}

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

    calls = {"count": 0}

    def _urlopen(req, timeout=0):  # noqa: ARG001
        url = req.full_url if hasattr(req, "full_url") else str(req)
        calls["count"] += 1
        if calls["count"] == 1 and url.endswith("/v1/models"):
            raise urllib.error.URLError("down")
        if url.endswith("/v1/models"):
            return _Resp(200, {"data": [{"id": "internvl3_5_8b"}]})
        if url.endswith("/v1/chat/completions"):
            return _Resp(200, {"choices": [{"message": {"content": "pong"}}]})
        raise AssertionError(url)

    class _Popen:
        def __init__(self, *args, **kwargs):  # noqa: ARG002
            self.pid = 999

        def wait(self, timeout=None):  # noqa: ARG002
            raise subprocess.TimeoutExpired(cmd="x", timeout=1.0)

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    monkeypatch.setattr("subprocess.Popen", _Popen)
    out = check_external_vllm_ready(require_completion=True)
    assert out["ok"] is True
    assert out["recovered"] is True
    assert out.get("orchestrator", {}).get("ok") is True
