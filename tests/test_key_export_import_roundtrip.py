import tempfile
import unittest
from pathlib import Path

from autocapture.storage.keys import export_keys, import_keys
from autocapture_nx.kernel.keyring import KeyRing


class KeyExportImportTests(unittest.TestCase):
    def test_export_import_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            keyring_path = Path(tmp) / "keyring.json"
            keyring = KeyRing.load(str(keyring_path))
            export_path = Path(tmp) / "export.json"
            export_keys(keyring, export_path)
            # Create a new keyring and import
            new_ring = KeyRing.load(str(Path(tmp) / "keyring2.json"))
            import_keys(new_ring, export_path)
            for purpose in keyring.purposes():
                self.assertTrue(
                    set(keyring.all_keys(purpose).keys()).issubset(set(new_ring.all_keys(purpose).keys()))
                )


if __name__ == "__main__":
    unittest.main()
