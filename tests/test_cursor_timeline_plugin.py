import unittest

from plugins.builtin.cursor_windows.plugin import _cursor_payload, _cursor_record


class DummyCursor:
    x = 5
    y = 6
    visible = True
    handle = 123


class CursorTimelinePluginTests(unittest.TestCase):
    def test_cursor_payload_includes_shape(self) -> None:
        payload = _cursor_payload(DummyCursor(), include_shape=True)
        self.assertEqual(payload["x"], 5)
        self.assertEqual(payload["y"], 6)
        self.assertTrue(payload["visible"])
        self.assertEqual(payload["handle"], 123)

    def test_cursor_payload_excludes_shape(self) -> None:
        payload = _cursor_payload(DummyCursor(), include_shape=False)
        self.assertNotIn("handle", payload)

    def test_cursor_record_fields(self) -> None:
        record_id, payload = _cursor_record(
            "run1",
            7,
            DummyCursor(),
            ts_utc="2026-01-01T00:00:00+00:00",
            include_shape=True,
            sample_hz=5,
        )
        self.assertEqual(record_id, "run1/cursor/7")
        self.assertEqual(payload["record_type"], "derived.cursor.sample")
        self.assertEqual(payload["run_id"], "run1")
        self.assertEqual(payload["ts_utc"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(payload["sample_hz"], 5)
        self.assertEqual(payload["cursor"]["x"], 5)
        self.assertEqual(payload["cursor"]["y"], 6)


if __name__ == "__main__":
    unittest.main()
