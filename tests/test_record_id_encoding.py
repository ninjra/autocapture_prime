import unittest

from autocapture_nx.kernel.ids import encode_record_id_component, decode_record_id_component


class RecordIdEncodingTests(unittest.TestCase):
    def test_encode_decode_roundtrip(self) -> None:
        record_id = "run1/segment/0"
        encoded = encode_record_id_component(record_id)
        decoded = decode_record_id_component(encoded)
        self.assertNotEqual(encoded, record_id)
        self.assertEqual(decoded, record_id)

    def test_decode_passthrough(self) -> None:
        self.assertEqual(decode_record_id_component("plain_id"), "plain_id")


if __name__ == "__main__":
    unittest.main()
