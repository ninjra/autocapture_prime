import unittest
import os
import tempfile

from autocapture_nx.kernel.loader import default_config_paths
from autocapture_nx.ux.facade import UXFacade

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
class DangerousToggleConfirmTests(unittest.TestCase):
    def test_enable_allow_raw_egress_requires_typed_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            app = None
            try:
                app = get_app()
                token = load_or_create_token(app.state.facade.config).token
                headers = {"Authorization": f"Bearer {token}"}
                client = TestClient(app)
                resp = client.post(
                    "/api/config",
                    headers=headers,
                    json={"patch": {"privacy": {"egress": {"allow_raw_egress": True}}}},
                )
                self.assertEqual(resp.status_code, 200)
                payload = resp.json()
                self.assertFalse(payload.get("ok", True))
                self.assertEqual(payload.get("error"), "confirmation_required")
                self.assertIn("privacy.egress.allow_raw_egress", payload.get("paths", []))

                resp2 = client.post(
                    "/api/config",
                    headers=headers,
                    json={"patch": {"privacy": {"egress": {"allow_raw_egress": True}}}, "confirm": "I UNDERSTAND"},
                )
                self.assertEqual(resp2.status_code, 200)
                payload2 = resp2.json()
                # Returns the merged config dict (not {ok:true}) on success.
                self.assertIsInstance(payload2, dict)
                self.assertTrue(payload2.get("privacy", {}).get("egress", {}).get("allow_raw_egress") is True)
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


def test_config_set_requires_confirmation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOCAPTURE_CONFIG_DIR", str(tmp_path))
    facade = UXFacade(paths=default_config_paths(), persistent=False, safe_mode=False)
    res = facade.config_set({"privacy": {"egress": {"allow_raw_egress": True}}})
    assert res["ok"] is False
    assert res["error"] == "confirmation_required"
    res2 = facade.config_set({"privacy": {"egress": {"allow_raw_egress": True}}}, confirm="I UNDERSTAND")
    assert res2["privacy"]["egress"]["allow_raw_egress"] is True
    facade.shutdown()
