import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.keyring import KeyRing, export_keyring_bundle, import_keyring_bundle


class KeyringBundleRoundtripTests(unittest.TestCase):
    def test_bundle_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            keyring_path = Path(tmp) / "keyring.json"
            keyring = KeyRing.load(str(keyring_path), require_protection=False, backend="portable_file")
            bundle_path = Path(tmp) / "bundle.json"
            export_keyring_bundle(keyring, path=str(bundle_path), passphrase="test-passphrase")

            imported = import_keyring_bundle(
                path=str(bundle_path),
                passphrase="test-passphrase",
                keyring_path=str(Path(tmp) / "keyring_imported.json"),
                require_protection=False,
                backend="portable_file",
                credential_name="autocapture.keyring.test",
            )

            for purpose in keyring.purposes():
                self.assertEqual(keyring.active_key_id_for(purpose), imported.active_key_id_for(purpose))
                self.assertEqual(set(keyring.all_keys(purpose).keys()), set(imported.all_keys(purpose).keys()))


if __name__ == "__main__":
    unittest.main()
