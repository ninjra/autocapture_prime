import unittest

from fastapi.testclient import TestClient

from autocapture.gateway.app import get_app


class GatewayPolicyBlockTests(unittest.TestCase):
    def test_cloud_blocked_by_default(self) -> None:
        client = TestClient(get_app())
        payload = {
            "messages": [{"role": "user", "content": "hello"}],
            "use_cloud": True,
        }
        resp = client.post("/v1/chat/completions", json=payload)
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
