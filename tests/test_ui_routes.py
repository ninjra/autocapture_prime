import unittest

from fastapi.testclient import TestClient

from autocapture.web.api import get_app


class UiRouteTests(unittest.TestCase):
    def test_ui_root_and_mount(self) -> None:
        client = TestClient(get_app())
        response_root = client.get("/")
        self.assertEqual(response_root.status_code, 200)
        response_ui = client.get("/ui")
        self.assertEqual(response_ui.status_code, 200)


if __name__ == "__main__":
    unittest.main()
