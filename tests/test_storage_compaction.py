import tempfile
import unittest
from pathlib import Path

from autocapture.storage.compaction import compact_derived
from plugins.builtin.storage_memory.plugin import InMemoryStore


class StorageCompactionTests(unittest.TestCase):
    def test_compaction_disabled_by_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = InMemoryStore()
            media = InMemoryStore()
            meta.put("run1/segment/0", {"record_type": "evidence.capture.segment"})
            meta.put("run1/derived.text.ocr/abc", {"record_type": "derived.text.ocr"})
            media.put("run1/segment/0", b"evidence")
            media.put("run1/derived.input.log/0", b"derived")

            lexical_path = Path(tmp) / "lexical.db"
            vector_path = Path(tmp) / "vector.db"
            lexical_path.write_text("index", encoding="utf-8")
            vector_path.write_text("index", encoding="utf-8")

            config = {
                "storage": {
                    "data_dir": tmp,
                    "metadata_path": str(Path(tmp) / "metadata"),
                    "lexical_path": str(lexical_path),
                    "vector_path": str(vector_path),
                }
            }
            result = compact_derived(meta, media, config, dry_run=False)
            self.assertEqual(result.derived_metadata, 1)
            self.assertEqual(result.derived_media, 1)
            self.assertTrue(result.dry_run)
            self.assertTrue(meta.get("run1/segment/0"))
            self.assertTrue(meta.get("run1/derived.text.ocr/abc"))
            self.assertTrue(media.get("run1/segment/0"))
            self.assertTrue(media.get("run1/derived.input.log/0"))
            self.assertTrue(lexical_path.exists())
            self.assertTrue(vector_path.exists())


if __name__ == "__main__":
    unittest.main()
