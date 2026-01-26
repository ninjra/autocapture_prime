import unittest

from autocapture.memory.verifier import Verifier


class VerifierEnforcedTests(unittest.TestCase):
    def test_requires_citations(self) -> None:
        verifier = Verifier()
        claims = [{"text": "hello", "citations": []}]
        with self.assertRaises(ValueError):
            verifier.verify(claims, {"s1"})


if __name__ == "__main__":
    unittest.main()
