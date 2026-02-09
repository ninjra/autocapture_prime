import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

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
class DoctorDbVersionsTests(unittest.TestCase):
    def test_doctor_includes_db_status_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_dir = Path(tmp) / "cfg"
            data_dir = Path(tmp) / "data"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            meta_path = data_dir / "metadata.db"
            con = sqlite3.connect(str(meta_path))
            try:
                con.execute("PRAGMA user_version=42")
                con.commit()
            finally:
                con.close()

            # Ensure the effective config points to temp DB paths (avoid repo writes).
            user_cfg = {
                "storage": {
                    "data_dir": str(data_dir),
                    "metadata_path": str(meta_path),
                    "lexical_path": str(data_dir / "lexical.db"),
                    "vector_path": str(data_dir / "vector.db"),
                    "audit_db_path": str(data_dir / "audit.db"),
                    "anchor": {"path": str(data_dir / "anchors.ndjson"), "sign": False},
                }
            }
            (cfg_dir / "user.json").write_text(json.dumps(user_cfg, indent=2, sort_keys=True), encoding="utf-8")

            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = str(cfg_dir)
            os.environ["AUTOCAPTURE_DATA_DIR"] = str(data_dir)
            app = None
            try:
                app = get_app()
                client = TestClient(app)
                doc = client.get("/api/doctor").json()
                self.assertIn("db_status", doc)
                dbs = doc["db_status"].get("dbs", [])
                names = {row.get("name") for row in dbs if isinstance(row, dict)}
                self.assertIn("metadata", names)
                meta = [row for row in dbs if isinstance(row, dict) and row.get("name") == "metadata"][0]
                self.assertTrue(meta.get("exists"))
                self.assertEqual(int(meta.get("sqlite_user_version") or 0), 42)
                self.assertTrue(isinstance(meta.get("sha256"), str) and len(meta.get("sha256")) == 64)
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

