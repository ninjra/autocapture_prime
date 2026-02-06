import os
import tempfile
import unittest

try:
    from fastapi.testclient import TestClient  # type: ignore
    from starlette.websockets import WebSocketDisconnect  # type: ignore

    from autocapture.web.api import get_app
    from autocapture_nx.kernel.auth import load_or_create_token
    from tests._fastapi_support import fastapi_testclient_usable
except Exception:  # pragma: no cover - optional dependency in some environments
    TestClient = None  # type: ignore[assignment]
    WebSocketDisconnect = None  # type: ignore[assignment]
    get_app = None  # type: ignore[assignment]
    load_or_create_token = None  # type: ignore[assignment]
    fastapi_testclient_usable = None  # type: ignore[assignment]

_FASTAPI_OK = bool(
    TestClient is not None
    and WebSocketDisconnect is not None
    and get_app is not None
    and load_or_create_token is not None
    and fastapi_testclient_usable is not None
    and fastapi_testclient_usable()
)

@unittest.skipUnless(
    _FASTAPI_OK,
    "fastapi TestClient unavailable or unusable",
)
class WebsocketTelemetryTests(unittest.TestCase):
    def test_websocket_requires_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            try:
                app = get_app()
                client = TestClient(app)
                with self.assertRaises(WebSocketDisconnect) as ctx:
                    with client.websocket_connect("/api/ws/telemetry"):
                        pass
                self.assertEqual(getattr(ctx.exception, "code", None), 4401)
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

    def test_websocket_payload_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            try:
                app = get_app()
                token = load_or_create_token(app.state.facade.config).token
                client = TestClient(app)
                with client.websocket_connect(f"/api/ws/telemetry?token={token}") as ws:
                    payload = ws.receive_json()
                self.assertIn("telemetry", payload)
                self.assertIn("scheduler", payload)
                self.assertIn("alerts", payload)
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
