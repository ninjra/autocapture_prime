import unittest

from fastapi.testclient import TestClient

from autocapture.web.api import get_app


class CitationOverlayContractTests(unittest.TestCase):
    def test_overlay_contract(self) -> None:
        client = TestClient(get_app())
        resp = client.post("/api/citations/overlay", json={"span_id": "s1"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("overlays", data)
        overlay = data["overlays"][0]
        self.assertIn("bbox", overlay)


if __name__ == "__main__":
    unittest.main()
