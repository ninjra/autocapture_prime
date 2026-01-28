import unittest

from autocapture_nx.kernel.transitions import missing_transitions


class LedgerTransitionTests(unittest.TestCase):
    def test_missing_transitions_detected(self) -> None:
        records = {
            "run1/segment/0": {"record_type": "evidence.capture.segment"},
            "run1/window/0": {"record_type": "evidence.window.meta"},
            "run1/derived.text.ocr/0": {"record_type": "derived.text.ocr"},
        }
        ledger_entries = [
            {"stage": "capture", "outputs": ["run1/segment/0"]},
            {"stage": "segment.seal", "outputs": ["run1/segment/0"]},
            {"stage": "window.meta", "outputs": ["run1/window/0"]},
            {"stage": "derived.extract", "outputs": ["run1/derived.text.ocr/0"]},
        ]
        missing = missing_transitions(records, ledger_entries)
        self.assertFalse(missing)

        ledger_entries.pop()
        missing = missing_transitions(records, ledger_entries)
        self.assertIn("run1/derived.text.ocr/0", missing)


if __name__ == "__main__":
    unittest.main()
