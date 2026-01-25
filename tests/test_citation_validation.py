import unittest

from autocapture.memory.citations import Citation, CitationValidator


class CitationValidationTests(unittest.TestCase):
    def test_invalid_span(self) -> None:
        validator = CitationValidator()
        with self.assertRaises(ValueError):
            validator.validate([Citation(span_id="missing")], {"s1"})


if __name__ == "__main__":
    unittest.main()
