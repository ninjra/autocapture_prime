import unittest
from unittest.mock import patch

from autocapture_nx.kernel.keyring import KeyRing


class KeyringProtectionTests(unittest.TestCase):
    def test_require_protection_fails_closed_when_unprotected(self) -> None:
        with patch("autocapture_nx.kernel.keyring.os.name", "nt"):
            with patch("autocapture_nx.kernel.keyring._protect", return_value=(b"secret", False)):
                with self.assertRaises(RuntimeError):
                    KeyRing._new_keyset("metadata", require_protection=True)


if __name__ == "__main__":
    unittest.main()
