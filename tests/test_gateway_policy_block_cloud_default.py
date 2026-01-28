import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from autocapture.gateway.app import get_app


class GatewayPolicyBlockTests(unittest.TestCase):
    def test_cloud_blocked_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            try:
                client = TestClient(get_app())
                payload = {
                    "messages": [{"role": "user", "content": "hello"}],
                    "use_cloud": True,
                }
                resp = client.post("/v1/chat/completions", json=payload)
                self.assertEqual(resp.status_code, 403)
            finally:
                if original_config is None:
                    os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_CONFIG_DIR"] = original_config
                if original_data is None:
                    os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_DATA_DIR"] = original_data


if __name__ == "__main__":
    unittest.main()
