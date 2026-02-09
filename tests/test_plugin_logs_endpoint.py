import os
import tempfile
import unittest
from pathlib import Path

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
class PluginLogsEndpointTests(unittest.TestCase):
    def test_logs_requires_token_even_for_get(self) -> None:
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
                plugin_id = "builtin.ocr.basic"
                run_id = str(app.state.facade.config.get("runtime", {}).get("run_id") or "run")
                log_path = Path(tmp) / "runs" / run_id / f"plugin_host_{plugin_id}.log"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text("hello\\nAuthorization: Bearer sk-test\\nworld\\n", encoding="utf-8")

                resp = client.get(f"/api/plugins/{plugin_id}/logs")
                self.assertEqual(resp.status_code, 401)

                ok = client.get(f"/api/plugins/{plugin_id}/logs", headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(ok.status_code, 200)
                data = ok.json()
                self.assertTrue(data.get("ok"))
                lines = data.get("lines", [])
                self.assertIn("hello", "\\n".join(lines))
                self.assertIn("world", "\\n".join(lines))
                self.assertNotIn("Bearer", "\\n".join(lines))
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

