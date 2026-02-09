import unittest

from autocapture_nx.kernel.derived_records import derived_text_record_id


class ExtractorCacheKeyTests(unittest.TestCase):
    def test_derived_ids_include_model_identity_digest(self) -> None:
        base = {"models": {"providers": {"test_provider": {"model_id": "m1", "revision": "r1"}}}}
        a1 = derived_text_record_id(
            kind="ocr",
            run_id="run",
            provider_id="test_provider",
            source_id="run/evidence.capture.frame/1",
            config=base,
        )
        a2 = derived_text_record_id(
            kind="ocr",
            run_id="run",
            provider_id="test_provider",
            source_id="run/evidence.capture.frame/1",
            config=base,
        )
        self.assertEqual(a1, a2)

        changed = {"models": {"providers": {"test_provider": {"model_id": "m1", "revision": "r2"}}}}
        b = derived_text_record_id(
            kind="ocr",
            run_id="run",
            provider_id="test_provider",
            source_id="run/evidence.capture.frame/1",
            config=changed,
        )
        self.assertNotEqual(a1, b)


if __name__ == "__main__":
    unittest.main()

