import unittest
from types import SimpleNamespace

from autocapture_nx.kernel.hashing import sha256_text
from plugins.builtin.window_metadata_windows.plugin import _build_window_payload


class WindowMetadataPayloadTests(unittest.TestCase):
    def test_payload_includes_raw_and_hash(self) -> None:
        monitor = SimpleNamespace(device="MONITOR1", rect=(0, 0, 1920, 1080))
        info = SimpleNamespace(
            title="Example App",
            process_path=r"C:\Apps\Example\app.exe",
            process_path_raw=r"\\Device\\HarddiskVolume2\\Apps\\Example\\app.exe",
            hwnd=101,
            rect=(10, 20, 300, 400),
            monitor=monitor,
        )
        payload = _build_window_payload(info)
        self.assertEqual(payload["title"], "Example App")
        self.assertEqual(payload["process_path"], r"C:\Apps\Example\app.exe")
        self.assertEqual(payload["process_path_raw"], r"\\Device\\HarddiskVolume2\\Apps\\Example\\app.exe")
        self.assertEqual(payload["process_path_hash"], sha256_text(r"C:\Apps\Example\app.exe"))
        self.assertEqual(payload["rect"], [10, 20, 300, 400])
        self.assertEqual(payload["monitor"]["device"], "MONITOR1")
        self.assertEqual(payload["monitor"]["rect"], [0, 0, 1920, 1080])


if __name__ == "__main__":
    unittest.main()
