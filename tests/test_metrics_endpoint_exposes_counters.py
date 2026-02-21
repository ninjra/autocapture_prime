import os
import tempfile
import unittest

try:
    from fastapi.testclient import TestClient  # type: ignore
    from autocapture.web.api import get_app
    from tests._fastapi_support import fastapi_testclient_usable
except Exception:  # pragma: no cover - optional dependency in some environments
    TestClient = None  # type: ignore[assignment]
    get_app = None  # type: ignore[assignment]
    fastapi_testclient_usable = None  # type: ignore[assignment]

_FASTAPI_OK = bool(
    TestClient is not None
    and get_app is not None
    and fastapi_testclient_usable is not None
    and fastapi_testclient_usable()
)

@unittest.skipUnless(_FASTAPI_OK, "fastapi TestClient unavailable or unusable")
class MetricsEndpointTests(unittest.TestCase):
    def test_metrics_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            try:
                client = TestClient(get_app())
                resp = client.get("/api/metrics")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertIn("counters", data)
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
