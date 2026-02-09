import os
import tempfile
import unittest

try:
    from fastapi.testclient import TestClient  # type: ignore
    from autocapture.web.api import get_app
    from tests._fastapi_support import fastapi_testclient_usable
except Exception:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]
    get_app = None  # type: ignore[assignment]
    fastapi_testclient_usable = None  # type: ignore[assignment]


_FASTAPI_OK = bool(
    TestClient is not None and get_app is not None and fastapi_testclient_usable is not None and fastapi_testclient_usable()
)


@unittest.skipUnless(_FASTAPI_OK, "fastapi TestClient unavailable or unusable")
class UiResourcePanelTests(unittest.TestCase):
    def test_status_banner_includes_cpu_ram_badges_and_status_payload_has_resources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            app = None
            try:
                app = get_app()
                client = TestClient(app)
                html = client.get("/ui/index.html").text
                self.assertIn("captureBannerCpu", html)
                self.assertIn("captureBannerRam", html)
                status = client.get("/api/status").json()
                self.assertIn("resources", status)
                self.assertIn("governor", status)
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

