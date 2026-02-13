from __future__ import annotations


class _Journal:
    def __init__(self):
        self.last = None

    def append_event(self, event_type, payload, **_kwargs):
        self.last = (event_type, dict(payload))
        return "evt_1"


class _Ledger:
    def append_entry(self, *_args, **_kwargs):
        return "ldg_1"


def test_journal_event_defaults_schema_version_for_evidence():
    from autocapture_nx.kernel.event_builder import EventBuilder

    j = _Journal()
    ledger = _Ledger()
    b = EventBuilder({"runtime": {"run_id": "run_1"}}, j, ledger, None)
    payload = {
        "record_type": "evidence.window.meta",
        "run_id": "run_1",
        "ts_utc": "2026-02-09T00:00:00Z",
        "window": {"title": "t"},
        # evidence.schema.json requires either content_hash or payload_hash.
        "payload_hash": "x" * 64,
    }
    b.journal_event("window.meta", payload, event_id="rid_1", ts_utc="2026-02-09T00:00:00Z")
    assert j.last is not None
    _event_type, stored = j.last
    assert stored.get("schema_version") == 1
