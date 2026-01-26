import io
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.keyring import KeyRing
from plugins.builtin.storage_encrypted.plugin import (
    BLOB_MAGIC,
    STREAM_MAGIC,
    DerivedKeyProvider,
    EncryptedBlobStore,
)


class EncryptedBlobStoreTests(unittest.TestCase):
    def test_blob_and_stream_formats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            keyring_path = Path(tmp) / "keyring.json"
            keyring = KeyRing.load(str(keyring_path))
            provider = DerivedKeyProvider(keyring, "media")
            store = EncryptedBlobStore(str(Path(tmp) / "media"), provider, "run1")

            record_id = "run1/segment/0"
            payload = b"secret"
            store.put(record_id, payload, ts_utc="2024-01-01T00:00:00+00:00")
            blob_path = next(
                Path(path)
                for path in store._path_candidates(record_id)
                if Path(path).exists()
            )
            content = blob_path.read_bytes()
            self.assertTrue(content.startswith(BLOB_MAGIC))
            self.assertNotIn(payload, content)

            stream_id = "run1/segment/1"
            store.put_stream(stream_id, io.BytesIO(payload), ts_utc="2024-01-02T00:00:00+00:00")
            stream_path = next(
                Path(path)
                for path in store._path_candidates(stream_id)
                if Path(path).exists()
            )
            stream_content = stream_path.read_bytes()
            self.assertTrue(stream_content.startswith(STREAM_MAGIC))


if __name__ == "__main__":
    unittest.main()
