from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autocapture_prime.config import load_prime_config
from services.chronicle_api.app import _call_hypervisor_query


class _DummyResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return dict(self._payload)


class _DummyClient:
    def __init__(self, payload: dict, sink: dict) -> None:
        self._payload = payload
        self._sink = sink

    def __enter__(self) -> "_DummyClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, json: dict, headers: dict | None = None) -> _DummyResponse:
        self._sink["url"] = str(url)
        self._sink["json"] = dict(json)
        self._sink["headers"] = dict(headers or {})
        return _DummyResponse(self._payload)


class ChronicleApiHypervisorQueryTests(unittest.TestCase):
    def test_call_hypervisor_query_localhost_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "cfg.yaml"
            cfg_path.write_text(
                "\n".join(
                    [
                        "chronicle_api:",
                        "  query_owner: hypervisor",
                        "  hypervisor_base_url: http://10.1.2.3:34221",
                        "  hypervisor_chat_path: /v1/chat/completions",
                    ]
                ),
                encoding="utf-8",
            )
            cfg = load_prime_config(cfg_path)
            with self.assertRaises(ValueError):
                _call_hypervisor_query(cfg, {"messages": [{"role": "user", "content": "hi"}]})

    def test_call_hypervisor_query_posts_expected_payload(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "cfg.yaml"
            cfg_path.write_text(
                "\n".join(
                    [
                        "chronicle_api:",
                        "  query_owner: hypervisor",
                        "  hypervisor_base_url: http://127.0.0.1:34221",
                        "  hypervisor_chat_path: /v1/chat/completions",
                        "  hypervisor_api_key: test_key_123",
                    ]
                ),
                encoding="utf-8",
            )
            cfg = load_prime_config(cfg_path)
            sink: dict = {}

            def _mk_client(*args, **kwargs):  # type: ignore[no-untyped-def]
                return _DummyClient({"ok": True, "id": "resp-1"}, sink)

            with patch("services.chronicle_api.app.httpx.Client", side_effect=_mk_client):
                out = _call_hypervisor_query(cfg, {"messages": [{"role": "user", "content": "hi"}]})

            self.assertTrue(bool(out.get("ok")))
            self.assertEqual(sink.get("url"), "http://127.0.0.1:34221/v1/chat/completions")
            self.assertIn("messages", sink.get("json", {}))
            headers = sink.get("headers", {})
            self.assertEqual(headers.get("Authorization"), "Bearer test_key_123")


if __name__ == "__main__":
    unittest.main()
