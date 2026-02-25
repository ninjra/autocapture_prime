from __future__ import annotations

import json
import unittest
from pathlib import Path


class TemporalQa40AnswerSchemaTests(unittest.TestCase):
    @staticmethod
    def _load_validator() -> object:
        try:
            import jsonschema  # type: ignore
        except Exception as exc:
            raise unittest.SkipTest(f"jsonschema not available: {exc}") from exc
        return jsonschema

    @staticmethod
    def _schema() -> dict:
        path = Path("docs/schemas/temporal_screenshot_qa_40_answer.schema.json")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_schema_accepts_minimal_ok_payload(self) -> None:
        jsonschema = self._load_validator()
        payload = {
            "status": "OK",
            "question_id": "TQ01",
            "time_window": {
                "start": "2026-02-24T00:00:00",
                "end": "2026-02-24T01:00:00",
                "timezone": "America/Denver",
                "source": "screenshot_time_overlay",
            },
            "answer": {"type": "object", "value": {"first_seen": "2026-02-24T00:05:00"}},
            "evidence": {
                "frames": [
                    {
                        "frame_id": "frame-1",
                        "screenshot_time": "2026-02-24T00:05:00",
                        "uia_refs": [{"node_id": "n1", "role": "window", "name": "Inbox"}],
                        "hid_refs": [{"event_id": "h1", "type": "click"}],
                    }
                ],
                "joins": [{"kind": "uia↔frame", "left": "frame_id", "right": "uia_frame_id"}],
            },
        }
        jsonschema.validate(payload, self._schema())

    def test_schema_rejects_ok_without_frame_evidence(self) -> None:
        jsonschema = self._load_validator()
        payload = {
            "status": "OK",
            "question_id": "TQ02",
            "time_window": {
                "start": "2026-02-24T00:00:00",
                "end": "2026-02-24T01:00:00",
                "timezone": "America/Denver",
                "source": "screenshot_time_overlay",
            },
            "answer": {"type": "list", "value": []},
            "evidence": {"frames": [], "joins": []},
        }
        with self.assertRaises(Exception):
            jsonschema.validate(payload, self._schema())


if __name__ == "__main__":
    unittest.main()

