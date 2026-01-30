import unittest

from autocapture.storage.retention import apply_evidence_retention


class NoDeletionModeTests(unittest.TestCase):
    def test_retention_skips_when_no_deletion_mode(self) -> None:
        config = {
            "storage": {
                "no_deletion_mode": True,
                "retention": {"evidence": "1d", "max_delete_per_run": 1},
            }
        }
        result = apply_evidence_retention(object(), object(), config, dry_run=True)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
