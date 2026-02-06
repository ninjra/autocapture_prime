import os
import tempfile
import unittest

try:
    from fastapi.testclient import TestClient  # type: ignore
    from autocapture.web.api import get_app
    from autocapture_nx.kernel.auth import load_or_create_token
    from tests._fastapi_support import fastapi_testclient_usable
except Exception:  # pragma: no cover - optional dependency in some environments
    TestClient = None  # type: ignore[assignment]
    get_app = None  # type: ignore[assignment]
    load_or_create_token = None  # type: ignore[assignment]
    fastapi_testclient_usable = None  # type: ignore[assignment]

_FASTAPI_OK = bool(
    TestClient is not None
    and get_app is not None
    and load_or_create_token is not None
    and fastapi_testclient_usable is not None
    and fastapi_testclient_usable()
)

@unittest.skipUnless(
    _FASTAPI_OK,
    "fastapi TestClient unavailable or unusable",
)
class CitationResolverApiTests(unittest.TestCase):
    def test_resolve_and_verify_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            try:
                app = get_app()
                token = load_or_create_token(app.state.facade.config).token
                client = TestClient(app)
                headers = {"Authorization": f"Bearer {token}"}
                resp = client.post("/api/citations/resolve", json={"citations": []}, headers=headers)
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertIn("ok", data)
                self.assertIn("resolved", data)
                self.assertIn("errors", data)

                resp_verify = client.post("/api/citations/verify", json={"citations": []}, headers=headers)
                self.assertEqual(resp_verify.status_code, 200)
                data_verify = resp_verify.json()
                self.assertIn("ok", data_verify)
                self.assertIn("errors", data_verify)
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
