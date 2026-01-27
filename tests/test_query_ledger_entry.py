import unittest

from autocapture_nx.kernel.query import run_query


class _Parser:
    def parse(self, _query: str) -> dict:
        return {"time_window": None}


class _Retrieval:
    def search(self, _query: str, time_window=None):
        _ = time_window
        return [{"record_id": "run1/segment/0", "score": 1, "ts_utc": "2026-01-01T00:00:00+00:00"}]


class _Answer:
    def build(self, claims):
        return {"claims": claims}


class _Metadata:
    def get(self, _key: str, default=None):
        return {"text": "hello world", "record_type": "evidence.capture.segment"}


class _EventBuilder:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def ledger_entry(self, stage: str, inputs: list[str], outputs: list[str], *, payload=None, **_kwargs) -> str:
        self.entries.append({"stage": stage, "inputs": inputs, "outputs": outputs, "payload": payload})
        return "hash"


class _System:
    def __init__(self) -> None:
        self.config = {
            "runtime": {"run_id": "run1"},
            "processing": {"on_query": {"allow_decode_extract": False}},
            "promptops": {"enabled": False},
        }
        self._caps = {
            "time.intent_parser": _Parser(),
            "retrieval.strategy": _Retrieval(),
            "answer.builder": _Answer(),
            "storage.metadata": _Metadata(),
            "event.builder": _EventBuilder(),
        }

    def get(self, name: str):
        return self._caps[name]


class QueryLedgerEntryTests(unittest.TestCase):
    def test_query_records_ledger_entry(self) -> None:
        system = _System()
        result = run_query(system, "hello")
        self.assertIn("answer", result)
        entries = system.get("event.builder").entries
        self.assertTrue(entries)
        entry = entries[-1]
        self.assertEqual(entry["stage"], "query.execute")
        payload = entry["payload"]
        self.assertEqual(payload["event"], "query.execute")
        self.assertEqual(payload["run_id"], "run1")
        self.assertEqual(payload["query"], "hello")
        self.assertEqual(payload["result_count"], 1)
        self.assertEqual(payload["extracted_count"], 0)
        self.assertEqual(entry["inputs"], ["run1/segment/0"])
        self.assertEqual(entry["outputs"], [])


if __name__ == "__main__":
    unittest.main()
