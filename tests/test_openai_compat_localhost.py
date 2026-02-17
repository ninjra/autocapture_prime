from __future__ import annotations

import threading
import time
import unittest
from unittest import mock

from autocapture_nx.inference.openai_compat import LocalhostOnlyError, OpenAICompatClient, _request_json, image_bytes_to_data_url


class OpenAICompatLocalhostTests(unittest.TestCase):
    def test_rejects_non_loopback_base_url(self) -> None:
        with self.assertRaises(LocalhostOnlyError):
            _ = OpenAICompatClient(base_url="https://example.com")

    def test_accepts_loopback_base_url(self) -> None:
        client = OpenAICompatClient(base_url="http://127.0.0.1:8000")
        self.assertEqual(client.base_url, "http://127.0.0.1:8000")

    def test_accepts_v1_base_url_without_double_prefix(self) -> None:
        client = OpenAICompatClient(base_url="http://127.0.0.1:8000/v1")
        self.assertEqual(client._endpoint_url("/v1/models"), "http://127.0.0.1:8000/v1/models")

    def test_managed_vlm_gate_limits_concurrency(self) -> None:
        active = {"count": 0, "max": 0}
        lock = threading.Lock()

        class _Resp:
            status = 200

            def __enter__(self):
                with lock:
                    active["count"] += 1
                    active["max"] = max(active["max"], active["count"])
                time.sleep(0.05)
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                with lock:
                    active["count"] -= 1
                return None

            def read(self, _size: int = -1):
                return b'{"ok":true}'

        def _worker():
            _request_json(
                method="GET",
                url="http://127.0.0.1:8000/v1/models",
                payload=None,
                timeout_s=1.0,
            )

        with mock.patch.dict("os.environ", {"AUTOCAPTURE_VLM_MAX_INFLIGHT": "1"}, clear=False):
            with mock.patch("urllib.request.urlopen", return_value=_Resp()):
                t1 = threading.Thread(target=_worker)
                t2 = threading.Thread(target=_worker)
                t1.start()
                t2.start()
                t1.join(timeout=2.0)
                t2.join(timeout=2.0)

        self.assertEqual(active["max"], 1)

    def test_image_data_url(self) -> None:
        data = b"\x89PNG\r\n\x1a\n"
        url = image_bytes_to_data_url(data)
        self.assertTrue(url.startswith("data:image/png;base64,"))


if __name__ == "__main__":
    unittest.main()
