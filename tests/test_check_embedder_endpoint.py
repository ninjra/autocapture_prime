from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest
from unittest import mock


def _load_module():
    path = pathlib.Path("tools/check_embedder_endpoint.py")
    spec = importlib.util.spec_from_file_location("check_embedder_endpoint_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CheckEmbedderEndpointTests(unittest.TestCase):
    def test_resolve_endpoint_settings_defaults(self) -> None:
        mod = _load_module()
        base_url, model = mod._resolve_endpoint_settings({})
        self.assertEqual(base_url, "http://127.0.0.1:8001")
        self.assertEqual(model, "BAAI/bge-small-en-v1.5")

    def test_resolve_endpoint_settings_from_config(self) -> None:
        mod = _load_module()
        cfg = {
            "plugins": {
                "settings": {
                    "builtin.embedder.vllm_localhost": {
                        "base_url": "http://127.0.0.1:9000/",
                        "model": "custom/model",
                    }
                }
            }
        }
        base_url, model = mod._resolve_endpoint_settings(cfg)
        self.assertEqual(base_url, "http://127.0.0.1:9000")
        self.assertEqual(model, "custom/model")

    def test_probe_success_sets_embedding_dim(self) -> None:
        mod = _load_module()

        def fake_http_json(*, method: str, url: str, timeout_s: float, payload=None):
            if url.endswith("/health"):
                return True, {"ok": True}, ""
            if url.endswith("/v1/models"):
                return True, {"data": [{"id": "embed-model"}]}, ""
            if url.endswith("/v1/embeddings"):
                return True, {"data": [{"embedding": [0.1, 0.2, 0.3]}]}, ""
            return False, {}, "unexpected"

        with mock.patch.object(mod, "_http_json", side_effect=fake_http_json):
            out = mod._probe("http://127.0.0.1:8001", "embed-model", 3.0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["checks"]["embeddings"]["embedding_dim"], 3)

    def test_probe_failure_is_not_ok(self) -> None:
        mod = _load_module()

        def fake_http_json(*, method: str, url: str, timeout_s: float, payload=None):
            return False, {}, "down"

        with mock.patch.object(mod, "_http_json", side_effect=fake_http_json):
            out = mod._probe("http://127.0.0.1:8001", "embed-model", 3.0)
        self.assertFalse(out["ok"])
        self.assertEqual(out["checks"]["health"]["error"], "down")


if __name__ == "__main__":
    unittest.main()

