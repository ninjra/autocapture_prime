from __future__ import annotations

import unittest

from autocapture_prime.cli import build_parser


class AutocapturePrimeCliTests(unittest.TestCase):
    def test_parser_has_required_commands(self) -> None:
        parser = build_parser()
        subactions = [a for a in parser._actions if getattr(a, "choices", None)]  # type: ignore[attr-defined]
        self.assertTrue(subactions)
        choices = set(subactions[0].choices.keys())  # type: ignore[index]
        self.assertIn("ingest", choices)
        self.assertIn("build-index", choices)
        self.assertIn("serve", choices)


if __name__ == "__main__":
    unittest.main()
