from __future__ import annotations

import json
import subprocess
import urllib.error

from autocapture_nx.runtime import http_localhost


class _Resp:
    def __init__(self, status: int, payload: dict) -> None:
        self.status = status
        self._payload = payload

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001, D401
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_request_json_uses_urllib_when_available(monkeypatch) -> None:
    def _urlopen(req, timeout=0):  # noqa: ARG001
        return _Resp(200, {"ok": True})

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    out = http_localhost.request_json(method="GET", url="http://127.0.0.1:34221/statusz", timeout_s=2.0)
    assert out["ok"] is True
    assert out["transport"] == "urllib"
    assert out["payload"] == {"ok": True}


def test_request_json_falls_back_to_curl_on_localhost_operation_not_permitted(monkeypatch) -> None:
    def _urlopen(req, timeout=0):  # noqa: ARG001
        raise urllib.error.URLError("[Errno 1] Operation not permitted")

    class _Proc:
        returncode = 0
        stderr = ""
        stdout = '{"ok":true}\n__STATUS__:200'

    def _run(cmd, capture_output=True, text=True, check=False):  # noqa: ARG001
        return _Proc()

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    monkeypatch.setattr("subprocess.run", _run)
    out = http_localhost.request_json(method="GET", url="http://127.0.0.1:8787/health", timeout_s=2.0)
    assert out["ok"] is True
    assert out["transport"] == "curl"
    assert out["payload"] == {"ok": True}


def test_request_json_does_not_curl_fallback_for_non_localhost(monkeypatch) -> None:
    def _urlopen(req, timeout=0):  # noqa: ARG001
        raise urllib.error.URLError("[Errno 1] Operation not permitted")

    def _run(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("curl fallback should not run for non-localhost URLs")

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    monkeypatch.setattr("subprocess.run", _run)
    out = http_localhost.request_json(method="GET", url="http://10.0.0.2:8000/v1/models", timeout_s=2.0)
    assert out["ok"] is False
    assert out["transport"] == "urllib"
    assert "Operation not permitted" in str(out["error"])


def test_request_json_curl_failure_is_reported(monkeypatch) -> None:
    def _urlopen(req, timeout=0):  # noqa: ARG001
        raise urllib.error.URLError("[Errno 1] Operation not permitted")

    def _run(cmd, capture_output=True, text=True, check=False):  # noqa: ARG001
        return subprocess.CompletedProcess(cmd, 7, "", "connect failed")

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    monkeypatch.setattr("subprocess.run", _run)
    out = http_localhost.request_json(method="GET", url="http://127.0.0.1:8011/health", timeout_s=2.0)
    assert out["ok"] is False
    assert out["transport"] == "curl"
    assert str(out["error"]).startswith("curl_failed")
