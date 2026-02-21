import json
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
class ErrorToDiagnosticsFlowTests(unittest.TestCase):
    def test_can_create_diagnostics_bundle_after_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_dir = Path(tmp) / "cfg"
            data_dir = Path(tmp) / "data"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            user_cfg = {"paths": {"config_dir": str(cfg_dir), "data_dir": str(data_dir)}, "storage": {"data_dir": str(data_dir)}}
            (cfg_dir / "user.json").write_text(json.dumps(user_cfg, indent=2, sort_keys=True), encoding="utf-8")

            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = str(cfg_dir)
            os.environ["AUTOCAPTURE_DATA_DIR"] = str(data_dir)
            app = None
            try:
                app = get_app()
                token = load_or_create_token(app.state.facade.config).token
                client = TestClient(app)

                err = client.post(
                    "/api/plugins/install",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"path": str(Path(tmp) / "does_not_exist"), "dry_run": True},
                ).json()
                self.assertFalse(err.get("ok"), err)

                bundle = client.post("/api/doctor/bundle", headers={"Authorization": f"Bearer {token}"}).json()
                self.assertTrue(bundle.get("ok"), bundle)
                path = Path(str(bundle.get("path") or ""))
                self.assertTrue(path.exists(), path)
                self.assertTrue(isinstance(bundle.get("sha256"), str) and len(bundle.get("sha256")) == 64)
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

