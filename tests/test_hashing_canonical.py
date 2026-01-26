import unittest

from autocapture.core.hashing import CanonicalJSONError, canonical_dumps, hash_canonical


class TestHashingCanonical(unittest.TestCase):
    def test_canonical_hash_deterministic(self) -> None:
        obj1 = {"b": 2, "a": 1}
        obj2 = {"a": 1, "b": 2}
        self.assertEqual(canonical_dumps(obj1), canonical_dumps(obj2))
        self.assertEqual(hash_canonical(obj1), hash_canonical(obj2))

    def test_unicode_normalization(self) -> None:
        obj1 = {"text": "e\u0301"}
        obj2 = {"text": "\u00e9"}
        self.assertEqual(canonical_dumps(obj1), canonical_dumps(obj2))

    def test_rejects_floats(self) -> None:
        with self.assertRaises(CanonicalJSONError):
            canonical_dumps({"pi": 3.14})


if __name__ == "__main__":
    unittest.main()
