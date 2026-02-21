import unittest

from autocapture.core.ids import stable_id, stable_id_from_text


class TestIdsStable(unittest.TestCase):
    def test_stable_id_deterministic(self) -> None:
        payload = {"b": 2, "a": 1}
        first = stable_id("span", payload)
        second = stable_id("span", {"a": 1, "b": 2})
        self.assertEqual(first, second)

    def test_stable_id_changes(self) -> None:
        first = stable_id("span", {"a": 1})
        second = stable_id("span", {"a": 2})
        self.assertNotEqual(first, second)

    def test_stable_id_from_text(self) -> None:
        first = stable_id_from_text("token", "hello")
        second = stable_id_from_text("token", "hello")
        self.assertEqual(first, second)

    def test_invalid_kind(self) -> None:
        with self.assertRaises(ValueError):
            stable_id("Span", {"a": 1})


if __name__ == "__main__":
    unittest.main()
