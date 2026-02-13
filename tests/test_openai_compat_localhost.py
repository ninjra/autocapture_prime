from __future__ import annotations

import unittest

from autocapture_nx.inference.openai_compat import LocalhostOnlyError, OpenAICompatClient, image_bytes_to_data_url


class OpenAICompatLocalhostTests(unittest.TestCase):
    def test_rejects_non_loopback_base_url(self) -> None:
        with self.assertRaises(LocalhostOnlyError):
            _ = OpenAICompatClient(base_url="https://example.com")

    def test_accepts_loopback_base_url(self) -> None:
        client = OpenAICompatClient(base_url="http://127.0.0.1:8000")
        self.assertEqual(client.base_url, "http://127.0.0.1:8000")

    def test_image_data_url(self) -> None:
        data = b"\x89PNG\r\n\x1a\n"
        url = image_bytes_to_data_url(data)
        self.assertTrue(url.startswith("data:image/png;base64,"))


if __name__ == "__main__":
    unittest.main()

