from __future__ import annotations

from autocapture_nx.runtime.conductor import run_job_with_retries


class FakeEventBuilder:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def ledger_entry(self, stage, inputs, outputs, *, payload=None, entry_id=None, ts_utc=None):
        self.entries.append({"stage": stage, "payload": payload, "ts_utc": ts_utc})
        return "fakehash"


def test_job_retries_and_records_attempts() -> None:
    builder = FakeEventBuilder()
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise ValueError("boom")

    # Avoid real sleeps in tests.
    run_job_with_retries(
        event_builder=builder,
        job_name="unit.flaky",
        fn=flaky,
        max_attempts=3,
        backoff_s=0.01,
        backoff_max_s=0.01,
        sleep_fn=lambda _s: None,
    )
    assert calls["n"] == 2
    attempts = [e for e in builder.entries if e["stage"] == "job.attempt"]
    assert [a["payload"]["attempt"] for a in attempts] == [1, 2]
    assert attempts[0]["payload"]["ok"] is False
    assert attempts[1]["payload"]["ok"] is True

