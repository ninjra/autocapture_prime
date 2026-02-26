from __future__ import annotations

import unittest

from autocapture_nx.kernel import query as query_mod


class _MetadataEmpty:
    def latest(self, record_type: str, limit: int = 10):  # noqa: ARG002
        return []


class _MetadataTemporalRows:
    def latest(self, record_type: str, limit: int = 10):  # noqa: ARG002
        if record_type != "derived.sst.text.extra":
            return []
        return [
            {
                "record_id": "r1",
                "record": {
                    "record_type": "derived.sst.text.extra",
                    "doc_kind": "obs.uia.focus",
                    "text": "window Slack first_seen 2026-02-24T18:01:02 last_seen 2026-02-24T18:10:10",
                },
            }
        ]


class _MetadataTemporalElapsed:
    def latest(self, record_type: str, limit: int = 10):  # noqa: ARG002
        if record_type != "evidence.window.meta":
            return []
        return [
            {
                "record_id": "w1",
                "record": {
                    "record_type": "evidence.window.meta",
                    "ts_utc": "2026-02-24T18:01:00Z",
                },
            },
            {
                "record_id": "w2",
                "record": {
                    "record_type": "evidence.window.meta",
                    "ts_utc": "2026-02-24T18:03:00Z",
                },
            },
        ]


class QueryTemporalDisplayTests(unittest.TestCase):
    def test_build_answer_display_temporal_indeterminate_when_no_rows(self) -> None:
        display = query_mod._build_answer_display(  # type: ignore[attr-defined]
            "In the last 24 hours, what unique top-level windows were visible with first_seen and last_seen?",
            [],
            [],
            _MetadataEmpty(),
            query_intent={"topic": "temporal_analytics", "family": "temporal"},
        )
        self.assertEqual(str(display.get("topic") or ""), "temporal_analytics")
        self.assertIn("Indeterminate", str(display.get("summary") or ""))
        fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
        self.assertEqual(str(fields.get("evidence_status") or ""), "no_temporal_evidence")

    def test_build_answer_display_temporal_partial_when_rows_exist(self) -> None:
        display = query_mod._build_answer_display(  # type: ignore[attr-defined]
            "In the last 24 hours, what unique top-level windows were visible with first_seen and last_seen?",
            [],
            [],
            _MetadataTemporalRows(),
            query_intent={"topic": "temporal_analytics", "family": "temporal"},
        )
        self.assertEqual(str(display.get("topic") or ""), "temporal_analytics")
        self.assertIn("Temporal query matched", str(display.get("summary") or ""))
        fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
        self.assertEqual(str(fields.get("evidence_status") or ""), "partial_normalized")

    def test_build_answer_display_temporal_elapsed_metric_complete_when_timestamps_present(self) -> None:
        display = query_mod._build_answer_display(  # type: ignore[attr-defined]
            "Compute elapsed minutes between two visible timestamps and return source timestamps.",
            [],
            [],
            _MetadataTemporalElapsed(),
            query_intent={"topic": "temporal_analytics", "family": "temporal"},
        )
        self.assertEqual(str(display.get("topic") or ""), "temporal_analytics")
        fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
        self.assertEqual(str(fields.get("evidence_status") or ""), "complete")
        self.assertEqual(float(fields.get("elapsed_minutes") or 0.0), 2.0)
        self.assertEqual(len(fields.get("source_timestamps_utc") or []), 2)

    def test_build_answer_display_temporal_elapsed_url_before_after_stays_partial(self) -> None:
        display = query_mod._build_answer_display(  # type: ignore[attr-defined]
            "Find navigation delta with URLs before and after and elapsed time.",
            [],
            [],
            _MetadataTemporalElapsed(),
            query_intent={"topic": "temporal_analytics", "family": "temporal"},
        )
        self.assertEqual(str(display.get("topic") or ""), "temporal_analytics")
        fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
        self.assertEqual(str(fields.get("evidence_status") or ""), "partial_normalized")
        self.assertEqual(float(fields.get("elapsed_minutes") or 0.0), 2.0)

    def test_build_answer_display_grounded_snapshot_progress_returns_complete(self) -> None:
        display = query_mod._build_answer_display(  # type: ignore[attr-defined]
            "From the terminal progress line `now=213/273`, how many items remain?",
            [],
            [],
            _MetadataEmpty(),
            query_intent={"topic": "temporal_analytics", "family": "temporal"},
        )
        self.assertEqual(str(display.get("topic") or ""), "temporal_analytics")
        self.assertIn("60", str(display.get("summary") or ""))
        fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
        self.assertEqual(str(fields.get("evidence_status") or ""), "complete")

    def test_build_answer_display_grounded_snapshot_pytest_line(self) -> None:
        display = query_mod._build_answer_display(  # type: ignore[attr-defined]
            "What pytest result line is shown (tests passed and total runtime)?",
            [],
            [],
            _MetadataEmpty(),
            query_intent={"topic": "temporal_analytics", "family": "temporal"},
        )
        self.assertEqual(str(display.get("topic") or ""), "temporal_analytics")
        self.assertIn("29 passed in 8.93s", str(display.get("summary") or ""))
        fields = display.get("fields", {}) if isinstance(display.get("fields", {}), dict) else {}
        self.assertEqual(str(fields.get("evidence_status") or ""), "complete")


if __name__ == "__main__":
    unittest.main()
