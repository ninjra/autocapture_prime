import unittest

try:
    from fastapi.testclient import TestClient  # type: ignore
    from autocapture.web.api import get_app
    from tests._fastapi_support import fastapi_testclient_usable
except Exception:  # pragma: no cover - optional dependency in some environments
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
class UiRouteTests(unittest.TestCase):
    def test_ui_root_and_mount(self) -> None:
        client = TestClient(get_app())
        response_root = client.get("/")
        self.assertEqual(response_root.status_code, 200)
        response_ui = client.get("/ui")
        self.assertEqual(response_ui.status_code, 200)


if __name__ == "__main__":
    unittest.main()
