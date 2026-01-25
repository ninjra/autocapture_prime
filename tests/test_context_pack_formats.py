import unittest

from autocapture.memory.context_pack import build_context_pack


class ContextPackFormatsTests(unittest.TestCase):
    def test_formats(self) -> None:
        spans = [{"span_id": "s1", "text": "hello"}]
        signals = {"tier": "FAST"}
        pack = build_context_pack(spans, signals)
        json_pack = pack.to_json()
        self.assertEqual(json_pack["format"], "json")
        self.assertIn("signals", json_pack)
        tron = pack.to_tron()
        self.assertTrue(tron.startswith("TRON/1.0"))
        self.assertIn("s1", tron)


if __name__ == "__main__":
    unittest.main()
