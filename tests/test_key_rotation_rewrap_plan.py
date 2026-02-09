import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.keyring import KeyRing
from plugins.builtin.storage_encrypted.plugin import DerivedKeyProvider, EncryptedJSONStore


class KeyRotationRewrapPlanTests(unittest.TestCase):
    def test_mixed_key_reads_and_rewrap_rotate_is_resumable_enough(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            keyring = KeyRing.load(str(root / "keyring.json"), backend="portable_file")
            provider = DerivedKeyProvider(keyring, "metadata")
            store = EncryptedJSONStore(str(root / "meta"), provider, run_id="run_test")

            store.put("rec1", {"record_type": "test", "run_id": "run_test", "ts_utc": "2026-02-09T00:00:00Z", "text": "hello"})
            first_active = keyring.active_key_id_for("metadata")
            keyring.rotate("metadata")
            second_active = keyring.active_key_id_for("metadata")
            self.assertNotEqual(first_active, second_active)

            # Mixed-key read: existing record remains readable after rotation (candidates include old keys).
            self.assertEqual(store.get("rec1", {}).get("text"), "hello")

            # New write uses the new active key_id.
            store.put("rec2", {"record_type": "test", "run_id": "run_test", "ts_utc": "2026-02-09T00:00:01Z", "text": "world"})

            # Rewrap: rotate() re-encrypts all records using the active key_id.
            rotated = store.rotate()
            self.assertGreaterEqual(rotated, 2)

            # Verify on-disk blobs now carry the active key_id.
            for path in root.rglob("*.json"):
                if path.name == "keyring.json":
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                if "key_id" in data:
                    self.assertEqual(data.get("key_id"), second_active)


if __name__ == "__main__":
    unittest.main()

