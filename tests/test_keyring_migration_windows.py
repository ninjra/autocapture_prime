import os
import tempfile
import unittest
import uuid
from pathlib import Path

from autocapture_nx.kernel.keyring import KeyRing


class KeyringMigrationWindowsTests(unittest.TestCase):
    def test_windows_credential_backend(self) -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Windows credential manager available on Windows only")
        with tempfile.TemporaryDirectory() as tmp:
            cred_name = f"autocapture.test.{uuid.uuid4()}"
            keyring_path = Path(tmp) / "keyring.json"
            ring = KeyRing.load(
                str(keyring_path),
                backend="windows_credential_manager",
                credential_name=cred_name,
            )
            active = ring.active_key_id
            ring2 = KeyRing.load(
                str(keyring_path),
                backend="windows_credential_manager",
                credential_name=cred_name,
            )
            self.assertEqual(active, ring2.active_key_id)


if __name__ == "__main__":
    unittest.main()
