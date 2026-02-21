import os
import tempfile
import unittest

from autocapture_nx.kernel.keyring import Keyring, KeyringStatus


class KeyringStatusTests(unittest.TestCase):
    def test_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "keyring.json")
            ring = Keyring.load(path)
            status = ring.status()
            self.assertIsInstance(status, KeyringStatus)
            self.assertEqual(status.active_key_ids.get("metadata"), ring.active_key_id)
            self.assertEqual(status.keyring_path, path)


if __name__ == "__main__":
    unittest.main()
