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


def _template_manifest() -> dict:
    return json.loads(Path("plugins/builtin/ocr_stub/plugin.json").read_text(encoding="utf-8"))


@unittest.skipUnless(_FASTAPI_OK, "fastapi TestClient unavailable or unusable")
class ExtensionManagerCoreFlowsTests(unittest.TestCase):
    def test_install_approve_enable_lock_snapshot_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_dir = Path(tmp) / "cfg"
            data_dir = Path(tmp) / "data"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            lockfile = cfg_dir / "plugin_locks.json"

            plugin_root = Path(tmp) / "local_plugin"
            plugin_root.mkdir(parents=True, exist_ok=True)
            manifest = _template_manifest()
            plugin_id = "local.flow.plugin"
            manifest["plugin_id"] = plugin_id
            manifest["version"] = "0.0.0-flow"
            (plugin_root / "plugin.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
            (plugin_root / "plugin.py").write_text("def create_plugin(plugin_id, ctx):\n    return object()\n", encoding="utf-8")

            user_cfg = {
                "paths": {"config_dir": str(cfg_dir), "data_dir": str(data_dir)},
                "storage": {"data_dir": str(data_dir)},
                "plugins": {
                    "hosting": {"mode": "inproc", "inproc_allow_all": True, "wsl_force_inproc": False},
                    "locks": {"lockfile": str(lockfile), "enforce": True},
                    "approvals": {"required": True},
                },
            }
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

                install = client.post(
                    "/api/plugins/install",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"path": str(plugin_root), "dry_run": False},
                ).json()
                self.assertTrue(install.get("ok"), install)
                self.assertTrue(lockfile.exists())

                perms = client.get(f"/api/plugins/{plugin_id}/permissions").json()
                self.assertTrue(perms.get("ok"), perms)
                digest = str(perms.get("digest") or "")

                approve = client.post(
                    f"/api/plugins/{plugin_id}/permissions/approve",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"accept_digest": digest, "confirm": f"APPROVE:{plugin_id}"},
                ).json()
                self.assertTrue(approve.get("ok"), approve)

                enable = client.post(f"/api/plugins/{plugin_id}/enable", headers={"Authorization": f"Bearer {token}"}).json()
                self.assertTrue(enable.get("ok"), enable)

                lifecycle = client.get(f"/api/plugins/{plugin_id}/lifecycle").json()
                self.assertTrue(lifecycle.get("ok"), lifecycle)
                self.assertTrue(lifecycle.get("enabled"), lifecycle)

                snap = client.post("/api/plugins/lock/snapshot", headers={"Authorization": f"Bearer {token}"}, json={"reason": "flow"}).json()
                self.assertTrue(snap.get("ok"), snap)
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
