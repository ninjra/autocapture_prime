import unittest

from fastapi.testclient import TestClient

from autocapture.gateway.app import get_app


class GatewaySchemaTests(unittest.TestCase):
    def test_schema_enforced(self) -> None:
        client = TestClient(get_app())
        resp = client.post("/v1/chat/completions", json={"messages": "bad"})
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
