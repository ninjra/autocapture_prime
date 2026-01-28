import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.keyring import KeyRing


class KeyringPurposeRotationTests(unittest.TestCase):
    def test_rotate_one_purpose_keeps_others(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keyring.json"
            ring = KeyRing.load(str(path))
            before_media = ring.active_key_id_for("media")
            before_anchor = ring.active_key_id_for("anchor")
            ring.rotate("metadata")
            self.assertEqual(before_media, ring.active_key_id_for("media"))
            self.assertEqual(before_anchor, ring.active_key_id_for("anchor"))


if __name__ == "__main__":
    unittest.main()
