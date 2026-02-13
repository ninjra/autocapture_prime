from __future__ import annotations

from typing import Any


def test_query_can_schedule_extract_job_when_blocked():
    from autocapture_nx.kernel.query import run_query_without_state

    class Store:
        def __init__(self, mapping: dict[str, Any]):
            self._m = dict(mapping)

        def get(self, key: str, default: Any = None) -> Any:
            return self._m.get(key, default)

        def put_new(self, key: str, value: Any) -> None:
            if key in self._m:
                raise FileExistsError(key)
            self._m[key] = value

        def keys(self):
            return list(self._m.keys())

    class Parser:
        def parse(self, query: str) -> dict[str, Any]:
            return {"query": query, "time_window": None}

    class Retrieval:
        def __init__(self, evidence_id: str):
            self._evidence_id = evidence_id

        def search(self, _query: str, time_window=None):  # noqa: ANN001
            return [{"record_id": self._evidence_id, "derived_id": None, "score": 1.0, "ts_utc": "2026-02-09T00:00:00Z"}]

        def trace(self):
            return []

    class Answer:
        def build(self, claims: list[dict[str, Any]]) -> dict[str, Any]:
            return {"state": "ok" if claims else "no_evidence", "claims": claims, "errors": []}

    class Events:
        def ledger_entry(self, *_a, **_k):  # noqa: ANN001
            return "ledger:test"

        def last_anchor(self):  # noqa: ANN001
            return "anchor:test"

    evidence_id = "run_test/evidence.capture.frame/0"
    metadata = Store(
        {
            evidence_id: {
                "schema_version": 1,
                "record_type": "evidence.capture.frame",
                "run_id": "run_test",
                "ts_utc": "2026-02-09T00:00:00Z",
                "content_hash": "deadbeef",
            }
        }
    )

    class System:
        def __init__(self):
            self.config = {
                "promptops": {"enabled": False, "require_citations": True},
                "runtime": {"run_id": "run_test", "activity": {"assume_idle_when_missing": False}},
                "processing": {"on_query": {"allow_decode_extract": False, "require_idle": True, "candidate_limit": 10}},
            }
            self._caps = {
                "time.intent_parser": Parser(),
                "retrieval.strategy": Retrieval(evidence_id),
                "answer.builder": Answer(),
                "storage.metadata": metadata,
                "event.builder": Events(),
            }

        def get(self, name: str):
            return self._caps[name]

    system = System()
    out = run_query_without_state(system, "extract please", schedule_extract=True)
    scheduled = out.get("scheduled_extract_job_id")
    assert scheduled
    job = metadata.get(scheduled)
    assert isinstance(job, dict)
    assert job.get("record_type") == "derived.job.extract"
    assert job.get("state") == "pending"

