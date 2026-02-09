import os
import tempfile
import unittest

try:
    from fastapi.testclient import TestClient  # type: ignore
    from autocapture.web.api import get_app
    from autocapture_nx.kernel.auth import load_or_create_token
    from tests._fastapi_support import fastapi_testclient_usable
except Exception:  # pragma: no cover
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


@unittest.skipUnless(_FASTAPI_OK, "fastapi TestClient unavailable or unusable")
class ConfigDiffViewerTests(unittest.TestCase):
    def test_config_diff_endpoint_and_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            app = None
            try:
                app = get_app()
                token = load_or_create_token(app.state.facade.config).token
                client = TestClient(app)

                diff1 = client.get("/api/config/diff").json()
                self.assertTrue(diff1.get("ok"), diff1)

                # Apply a safe patch.
                resp = client.post(
                    "/api/config",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"patch": {"time": {"timezone": "UTC"}}},
                )
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertTrue(data.get("ok", True) or data.get("error") is None)

                diff2 = client.get("/api/config/diff").json()
                user_diff = diff2.get("diff_user_to_effective", [])
                paths = {row.get("path") for row in user_diff if isinstance(row, dict)}
                self.assertIn("time.timezone", paths)
            finally:
                try:
                    if app is not None:
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

