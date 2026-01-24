import unittest

from autocapture_nx.kernel.canonical_json import dumps, CanonicalJSONError


class CanonicalJSONTests(unittest.TestCase):
    def test_sorted_keys(self):
        data = {"b": 1, "a": 2}
        self.assertEqual(dumps(data), '{"a":2,"b":1}')

    def test_rejects_float(self):
        with self.assertRaises(CanonicalJSONError):
            dumps({"a": 1.5})


if __name__ == "__main__":
    unittest.main()
