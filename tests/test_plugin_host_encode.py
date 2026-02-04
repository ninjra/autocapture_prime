import json
import unittest
from pathlib import Path

from autocapture_nx.plugin_system import host as host_module


class PluginHostEncodeTests(unittest.TestCase):
    def test_encode_tuple_with_bytes_is_jsonable(self) -> None:
        payload = ("key-id", b"\x01\x02\x03")
        encoded = host_module._encode(payload)
        json.dumps(encoded)
        self.assertIsInstance(encoded, list)

    def test_encode_path_is_jsonable(self) -> None:
        encoded = host_module._encode(Path("/tmp/example.txt"))
        json.dumps(encoded)
        self.assertIsInstance(encoded, str)


if __name__ == "__main__":
    unittest.main()
