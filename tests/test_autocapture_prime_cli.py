from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr

from autocapture_prime.cli import build_parser, main


class AutocapturePrimeCliTests(unittest.TestCase):
    def test_parser_wraps_nx_commands(self) -> None:
        parser = build_parser()
        subactions = [a for a in parser._actions if getattr(a, "choices", None)]  # type: ignore[attr-defined]
        self.assertTrue(subactions)
        choices = set(subactions[0].choices.keys())  # type: ignore[index]
        self.assertIn("query", choices)
        self.assertIn("batch", choices)
        self.assertIn("handoff", choices)

    def test_main_prints_deprecation_and_forwards(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = main(["status"])
        self.assertEqual(code, 0)
        self.assertIn("deprecated", stderr.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
