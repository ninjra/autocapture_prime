import unittest

from autocapture_nx.kernel.model_output_records import build_model_output_record, model_output_record_id
from autocapture_nx.kernel.schema_registry import SchemaRegistry


class ModelOutputRecordTests(unittest.TestCase):
    def test_build_model_output_record_is_canonical_and_validates(self) -> None:
        config = {"runtime": {"run_id": "run1"}, "models": {"vlm_prompt": "Describe."}}
        source_id = "run1/evidence.capture.frame/abc"
        source_record = {"run_id": "run1", "record_type": "evidence.capture.frame", "ts_utc": "2026-02-10T00:00:00+00:00"}

        # Include floats in the raw response: they should be preserved in output_json
        # but must not break canonical hashing of the derived record itself.
        response = {"text": "hello", "confidence": 0.123, "nested": {"x": 1.5}}
        payload = build_model_output_record(
            modality="vlm",
            provider_id="vlm.test",
            response=response,
            extracted_text="hello",
            source_id=source_id,
            source_record=source_record,
            config=config,
            ts_utc="2026-02-10T00:00:00+00:00",
        )
        self.assertEqual(payload["record_type"], "derived.model.output")
        self.assertEqual(payload["modality"], "vlm")
        self.assertIn("payload_hash", payload)
        self.assertIn("output_json", payload)
        self.assertIn('"confidence":0.123', payload["output_json"])

        record_id = model_output_record_id(
            modality="vlm",
            run_id="run1",
            provider_id="vlm.test",
            source_id=source_id,
            model_digest=str(payload.get("model_digest") or ""),
        )
        self.assertIn("/derived.model.output/", record_id)

        reg = SchemaRegistry()
        schema = reg.load_schema_path("contracts/model_output_record.schema.json")
        issues = reg.validate(schema, payload)
        self.assertEqual(issues, [], msg=reg.format_issues(issues))


if __name__ == "__main__":
    unittest.main()

