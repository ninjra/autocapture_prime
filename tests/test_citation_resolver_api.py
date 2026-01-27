import unittest

from fastapi.testclient import TestClient

from autocapture.web.api import get_app


class CitationResolverApiTests(unittest.TestCase):
    def test_resolve_and_verify_endpoints(self) -> None:
        client = TestClient(get_app())
        resp = client.post("/api/citations/resolve", json={"citations": []})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("ok", data)
        self.assertIn("resolved", data)
        self.assertIn("errors", data)

        resp_verify = client.post("/api/citations/verify", json={"citations": []})
        self.assertEqual(resp_verify.status_code, 200)
        data_verify = resp_verify.json()
        self.assertIn("ok", data_verify)
        self.assertIn("errors", data_verify)


if __name__ == "__main__":
    unittest.main()
