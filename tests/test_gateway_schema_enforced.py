import unittest

try:
    from fastapi.testclient import TestClient  # type: ignore
    from autocapture.gateway.app import get_app
    from tests._fastapi_support import fastapi_testclient_usable
except Exception:  # pragma: no cover
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
class GatewaySchemaTests(unittest.TestCase):
    def test_schema_enforced(self) -> None:
        client = TestClient(get_app())
        resp = client.post("/v1/chat/completions", json={"messages": "bad"})
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
