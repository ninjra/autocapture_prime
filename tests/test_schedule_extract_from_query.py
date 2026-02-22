from __future__ import annotations

from typing import Any
from unittest.mock import patch


def test_query_never_schedules_extract_job_when_blocked():
    from autocapture_nx.kernel.query import run_query_without_state
    from autocapture_nx.kernel import query as query_mod

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
    query_mod._reset_query_contract_counters_for_tests()
    out = run_query_without_state(system, "extract please", schedule_extract=True)
    assert out.get("scheduled_extract_job_id") in (None, "")
    processing = out.get("processing", {}) if isinstance(out.get("processing"), dict) else {}
    extraction = processing.get("extraction", {}) if isinstance(processing.get("extraction"), dict) else {}
    assert extraction.get("blocked") is True
    assert extraction.get("blocked_reason") == "query_read_only"
    assert len([k for k in metadata.keys() if "/derived.job.extract/" in str(k)]) == 0
    metrics = out.get("processing", {}).get("query_contract_metrics", {}) if isinstance(out.get("processing", {}).get("query_contract_metrics", {}), dict) else {}
    assert int(metrics.get("query_schedule_extract_requests_total", 0) or 0) == 1


def test_query_read_only_path_without_schedule_extract_remains_noop():
    from autocapture_nx.kernel.query import run_query_without_state
    from autocapture_nx.kernel import query as query_mod

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

    evidence_id = "run_test/evidence.capture.frame/1"
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
                "processing": {"on_query": {"allow_decode_extract": True, "require_idle": True, "candidate_limit": 10}},
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
    query_mod._reset_query_contract_counters_for_tests()
    out = run_query_without_state(system, "status", schedule_extract=False)
    assert out.get("scheduled_extract_job_id") in (None, "")
    processing = out.get("processing", {}) if isinstance(out.get("processing"), dict) else {}
    extraction = processing.get("extraction", {}) if isinstance(processing.get("extraction"), dict) else {}
    assert extraction.get("blocked") is True
    assert extraction.get("blocked_reason") == "query_read_only"
    evaluation = out.get("evaluation", {}) if isinstance(out.get("evaluation"), dict) else {}
    assert evaluation.get("blocked_extract") is True
    assert evaluation.get("blocked_reason") == "query_read_only"
    metrics = out.get("processing", {}).get("query_contract_metrics", {}) if isinstance(out.get("processing", {}).get("query_contract_metrics", {}), dict) else {}
    assert int(metrics.get("query_schedule_extract_requests_total", 0) or 0) == 0
    assert len([k for k in metadata.keys() if "/derived.job.extract/" in str(k)]) == 0


def test_query_fast_cache_returns_instant_cached_result_for_repeat_query():
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
            self.calls = 0

        def search(self, _query: str, time_window=None):  # noqa: ANN001
            self.calls += 1
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

    evidence_id = "run_test_cache/evidence.capture.frame/1"
    metadata = Store(
        {
            evidence_id: {
                "schema_version": 1,
                "record_type": "evidence.capture.frame",
                "run_id": "run_test_cache",
                "ts_utc": "2026-02-09T00:00:00Z",
                "content_hash": "deadbeef",
            }
        }
    )
    retrieval = Retrieval(evidence_id)

    class System:
        def __init__(self):
            self.config = {
                "promptops": {"enabled": False, "require_citations": True},
                "runtime": {"run_id": "run_test_cache", "activity": {"assume_idle_when_missing": False}},
                "query": {"fast_cache": {"enabled": True, "ttl_s": 30.0, "max_entries": 16}},
                "processing": {"on_query": {"allow_decode_extract": False, "require_idle": True, "candidate_limit": 10}},
            }
            self._caps = {
                "time.intent_parser": Parser(),
                "retrieval.strategy": retrieval,
                "answer.builder": Answer(),
                "storage.metadata": metadata,
                "event.builder": Events(),
            }

        def get(self, name: str):
            return self._caps[name]

    system = System()
    first = run_query_without_state(system, "status", schedule_extract=False)
    second = run_query_without_state(system, "status", schedule_extract=False)
    assert retrieval.calls == 1
    first_cache = ((first.get("processing") or {}).get("query_cache") or {}) if isinstance(first, dict) else {}
    second_cache = ((second.get("processing") or {}).get("query_cache") or {}) if isinstance(second, dict) else {}
    assert bool(first_cache.get("hit", False)) is False
    assert bool(second_cache.get("hit", False)) is True


def test_query_synthesizer_not_enabled_by_golden_profile_without_strict_env():
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
        def search(self, _query: str, time_window=None):  # noqa: ANN001
            _ = time_window
            return [{"record_id": evidence_id, "derived_id": derived_id, "score": 1.0, "ts_utc": "2026-02-09T00:00:00Z"}]

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

    class Synth:
        def __init__(self) -> None:
            self.calls = 0

        def synthesize(self, _query: str, _evidence: list[dict[str, Any]], *, max_claims: int = 3) -> dict[str, Any]:
            _ = max_claims
            self.calls += 1
            return {"claims": []}

    evidence_id = "run_test/evidence.capture.frame/2"
    derived_id = "run_test/derived.text.ocr/test"
    metadata = Store(
        {
            evidence_id: {
                "schema_version": 1,
                "record_type": "evidence.capture.frame",
                "run_id": "run_test",
                "ts_utc": "2026-02-09T00:00:00Z",
                "content_hash": "hash-evidence",
            },
            derived_id: {
                "schema_version": 1,
                "record_type": "derived.text.ocr",
                "run_id": "run_test",
                "source_id": evidence_id,
                "text": "Observed browser window and terminal.",
                "content_hash": "hash-derived",
                "ts_utc": "2026-02-09T00:00:00Z",
            },
        }
    )
    synth = Synth()

    class System:
        def __init__(self):
            self.config = {
                "promptops": {"enabled": False, "require_citations": True},
                "runtime": {"run_id": "run_test", "activity": {"assume_idle_when_missing": False}},
                "processing": {"on_query": {"allow_decode_extract": False, "require_idle": True, "candidate_limit": 10}},
                "plugins": {"settings": {"__golden_profile": {"enable_synthesizer": True}}},
            }
            self._caps = {
                "time.intent_parser": Parser(),
                "retrieval.strategy": Retrieval(),
                "answer.builder": Answer(),
                "storage.metadata": metadata,
                "event.builder": Events(),
                "answer.synthesizer": synth,
            }

        def get(self, name: str):
            return self._caps[name]

    with patch.dict("os.environ", {"AUTOCAPTURE_GOLDEN_STRICT": "", "AUTOCAPTURE_ENABLE_SYNTHESIZER": ""}, clear=False):
        _ = run_query_without_state(System(), "what is visible now", schedule_extract=False)
    assert synth.calls == 0


def test_query_synthesizer_enabled_by_golden_profile_when_strict_env_is_set():
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
        def search(self, _query: str, time_window=None):  # noqa: ANN001
            _ = time_window
            return [{"record_id": evidence_id, "derived_id": derived_id, "score": 1.0, "ts_utc": "2026-02-09T00:00:00Z"}]

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

    class Synth:
        def __init__(self) -> None:
            self.calls = 0

        def synthesize(self, _query: str, _evidence: list[dict[str, Any]], *, max_claims: int = 3) -> dict[str, Any]:
            _ = max_claims
            self.calls += 1
            return {"claims": []}

    evidence_id = "run_test/evidence.capture.frame/3"
    derived_id = "run_test/derived.text.ocr/test2"
    metadata = Store(
        {
            evidence_id: {
                "schema_version": 1,
                "record_type": "evidence.capture.frame",
                "run_id": "run_test",
                "ts_utc": "2026-02-09T00:00:00Z",
                "content_hash": "hash-evidence-2",
            },
            derived_id: {
                "schema_version": 1,
                "record_type": "derived.text.ocr",
                "run_id": "run_test",
                "source_id": evidence_id,
                "text": "Observed Slack and browser tabs.",
                "content_hash": "hash-derived-2",
                "ts_utc": "2026-02-09T00:00:00Z",
            },
        }
    )
    synth = Synth()

    class System:
        def __init__(self):
            self.config = {
                "promptops": {"enabled": False, "require_citations": True},
                "runtime": {"run_id": "run_test", "activity": {"assume_idle_when_missing": False}},
                "processing": {"on_query": {"allow_decode_extract": False, "require_idle": True, "candidate_limit": 10}},
                "plugins": {"settings": {"__golden_profile": {"enable_synthesizer": True}}},
            }
            self._caps = {
                "time.intent_parser": Parser(),
                "retrieval.strategy": Retrieval(),
                "answer.builder": Answer(),
                "storage.metadata": metadata,
                "event.builder": Events(),
                "answer.synthesizer": synth,
            }

        def get(self, name: str):
            return self._caps[name]

    with patch.dict("os.environ", {"AUTOCAPTURE_GOLDEN_STRICT": "1", "AUTOCAPTURE_ENABLE_SYNTHESIZER": ""}, clear=False):
        _ = run_query_without_state(System(), "what is visible now", schedule_extract=False)
    assert synth.calls == 1
