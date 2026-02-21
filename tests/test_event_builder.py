import unittest
from unittest.mock import patch

from autocapture_nx.kernel.event_builder import EventBuilder


class _Journal:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, dict]] = []

    def append_event(self, event_type: str, payload: dict, **kwargs) -> str:
        self.calls.append((event_type, payload, kwargs))
        return kwargs.get("event_id") or "event"


class _Ledger:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def append(self, entry: dict) -> str:
        self.entries.append(entry)
        return "hash"


def _config() -> dict:
    return {"runtime": {"run_id": "run1", "timezone": "UTC"}}


class EventBuilderTests(unittest.TestCase):
    def test_policy_snapshot_cached(self) -> None:
        journal = _Journal()
        ledger = _Ledger()
        builder = EventBuilder(_config(), journal, ledger)
        with patch("autocapture_nx.kernel.event_builder.policy_snapshot_hash", side_effect=["h1", "h2"]) as mock_hash:
            first = builder.policy_snapshot_hash()
            builder._config["runtime"]["timezone"] = "UTC+1"
            second = builder.policy_snapshot_hash()
        self.assertEqual(first, second)
        self.assertEqual(mock_hash.call_count, 1)

    def test_ledger_entry_prefix_and_policy_hash(self) -> None:
        journal = _Journal()
        ledger = _Ledger()
        with patch("autocapture_nx.kernel.event_builder.policy_snapshot_hash", return_value="policyhash"):
            builder = EventBuilder(_config(), journal, ledger)
            ledger_hash = builder.ledger_entry("capture", inputs=[], outputs=["out"])
        self.assertEqual(ledger_hash, "hash")
        self.assertEqual(len(ledger.entries), 1)
        entry = ledger.entries[0]
        self.assertEqual(entry["policy_snapshot_hash"], "policyhash")
        self.assertTrue(entry["entry_id"].startswith("run1/ledger.capture/"))


if __name__ == "__main__":
    unittest.main()
