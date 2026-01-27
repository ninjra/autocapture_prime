import unittest

from autocapture.core.hashing import hash_text, normalize_text


class TextNormalizationTests(unittest.TestCase):
    def test_equivalent_forms_normalize_to_same_hash(self) -> None:
        a = "Cafe\u0301\r\n  hello\tworld  "
        b = "Café\nhello world"
        norm_a = normalize_text(a)
        norm_b = normalize_text(b)
        self.assertEqual(norm_a, norm_b)
        self.assertEqual(hash_text(norm_a), hash_text(norm_b))

    def test_normalize_text_is_idempotent(self) -> None:
        text = "  A\tB\r\nC  "
        norm = normalize_text(text)
        self.assertEqual(normalize_text(norm), norm)


if __name__ == "__main__":
    unittest.main()

