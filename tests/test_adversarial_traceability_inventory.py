import unittest
from pathlib import Path

from tools.traceability.adversarial_redesign_inventory import iter_redesign_items


class AdversarialTraceabilityInventoryTests(unittest.TestCase):
    def test_inventory_finds_all_ids(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        doc = repo_root / "docs" / "autocapture_prime_adversarial_redesign.md"
        items = iter_redesign_items(doc)
        ids = [it.item_id for it in items]
        self.assertEqual(len(ids), 92)
        self.assertEqual(len(set(ids)), 92)
        self.assertIn("FND-01", ids)
        self.assertIn("SEC-05", ids)


if __name__ == "__main__":
    unittest.main()

