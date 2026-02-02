import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from autocapture.web.api import get_app
from autocapture_nx.kernel.auth import load_or_create_token


class WebAuthMiddlewareTests(unittest.TestCase):
    def test_post_requires_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            try:
                app = get_app()
                token = load_or_create_token(app.state.facade.config).token
                client = TestClient(app)
                resp = client.post("/api/query", json={"query": "hello"})
                self.assertEqual(resp.status_code, 401)
                resp_ok = client.post(
                    "/api/query",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"query": "hello"},
                )
                self.assertEqual(resp_ok.status_code, 200)
            finally:
                try:
                    app.state.facade.shutdown()
                except Exception:
                    pass
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
