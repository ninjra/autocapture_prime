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


@unittest.skipUnless(_FASTAPI_OK, "fastapi TestClient unavailable or unusable")
class EgressApprovalWorkflowTests(unittest.TestCase):
    def test_approval_requires_token_for_write_and_updates_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            try:
                app = get_app()
                client = TestClient(app)
                token = load_or_create_token(app.state.facade.config).token

                # Create a pending approval request via the approval store.
                with app.state.facade._kernel_mgr.session() as system:  # type: ignore[attr-defined]
                    self.assertIsNotNone(system)
                    assert system is not None
                    self.assertTrue(system.has("egress.approval_store"))
                    store = system.get("egress.approval_store")
                    req = store.request(packet_hash="deadbeef", policy_id="policy", schema_version=1)
                approval_id = req.get("approval_id")
                self.assertTrue(approval_id)

                # Pending request is visible via GET (local-only boundary).
                resp = client.get("/api/egress/requests")
                self.assertEqual(resp.status_code, 200)
                payload = resp.json()
                ids = {r.get("approval_id") for r in payload.get("requests", [])}
                self.assertIn(approval_id, ids)

                # Approve is a POST and must be authorized.
                resp_unauth = client.post("/api/egress/approve", json={"approval_id": approval_id})
                self.assertEqual(resp_unauth.status_code, 401)

                resp_ok = client.post(
                    "/api/egress/approve",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"approval_id": approval_id, "ttl_s": 60},
                )
                self.assertEqual(resp_ok.status_code, 200)
                token_payload = resp_ok.json()
                self.assertIn("token", token_payload)
                self.assertEqual(token_payload.get("approval_id"), approval_id)
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

