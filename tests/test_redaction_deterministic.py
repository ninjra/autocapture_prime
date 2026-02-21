import unittest

from autocapture.egress.sanitize import sanitize_json_for_export, redaction_metadata


class RedactionDeterminismTests(unittest.TestCase):
    def test_redaction_is_deterministic_and_no_raw_values_leak(self) -> None:
        key = b"\x00" * 32
        payload = {
            "msg": "Email me at alice@example.com or call (555) 123-4567.",
            "nested": ["bob@example.com", {"ssn": "123-45-6789"}],
        }
        out1, entries1 = sanitize_json_for_export(payload, key=key, recognizers=["email", "phone", "ssn"])
        out2, entries2 = sanitize_json_for_export(payload, key=key, recognizers=["email", "phone", "ssn"])
        self.assertEqual(out1, out2)
        self.assertEqual([e.token for e in entries1], [e.token for e in entries2])

        meta = redaction_metadata(entries1)
        meta_str = str(meta)
        # Ensure raw PII values do not appear in metadata.
        self.assertNotIn("alice@example.com", meta_str)
        self.assertNotIn("bob@example.com", meta_str)
        self.assertNotIn("123-45-6789", meta_str)
        self.assertNotIn("555", meta_str)


if __name__ == "__main__":
    unittest.main()

