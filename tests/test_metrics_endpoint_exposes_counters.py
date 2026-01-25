import unittest

from fastapi.testclient import TestClient

from autocapture.web.api import get_app


class MetricsEndpointTests(unittest.TestCase):
    def test_metrics_endpoint(self) -> None:
        client = TestClient(get_app())
        resp = client.get("/api/metrics")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("counters", data)


if __name__ == "__main__":
    unittest.main()
