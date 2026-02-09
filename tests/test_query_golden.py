import json
import unittest
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.query import run_query_without_state


class _Store:
    def __init__(self, mapping: dict[str, Any]) -> None:
        self._m = dict(mapping)

    def get(self, key: str, default: Any = None) -> Any:
        return self._m.get(key, default)

    def keys(self):
        return list(self._m.keys())


class _Parser:
    def parse(self, query: str) -> dict[str, Any]:
        return {"query": query, "time_window": None}


class _Retrieval:
    def __init__(self, metadata: _Store) -> None:
        self._m = metadata

    def search(self, query: str, time_window=None):  # noqa: ANN001
        q = str(query or "").casefold()
        hits = []
        if "chill instrumental" in q:
            hits.append({"record_id": "run_test/derived.text.ocr/test_provider/song", "derived_id": None})
        if "assigned" in q:
            hits.append({"record_id": "run_test/derived.text.ocr/test_provider/quorum", "derived_id": None})
        return hits


class _Answer:
    def build(self, claims: list[dict[str, Any]]) -> dict[str, Any]:
        return {"state": "ok" if claims else "no_evidence", "claims": claims, "errors": []}


class _Events:
    def ledger_entry(self, *_a, **_k):  # noqa: ANN001
        return "ledger:test"

    def last_anchor(self):  # noqa: ANN001
        return "anchor:test"


class _System:
    def __init__(self, metadata: _Store) -> None:
        self.config = {
            "promptops": {"enabled": False, "require_citations": True},
            "processing": {"on_query": {"allow_decode_extract": False, "require_idle": True}},
            "runtime": {"activity": {"assume_idle_when_missing": False}},
        }
        self._caps = {
            "time.intent_parser": _Parser(),
            "retrieval.strategy": _Retrieval(metadata),
            "answer.builder": _Answer(),
            "storage.metadata": metadata,
            "event.builder": _Events(),
        }

    def get(self, name: str):
        return self._caps[name]


def _load_fixture(name: str) -> dict[str, Any]:
    path = Path("tests/fixtures/query_golden") / name
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_ts(obj: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(obj, sort_keys=True))
    prov = out.get("provenance", {})
    if isinstance(prov, dict) and "generated_at_utc" in prov:
        prov["generated_at_utc"] = "<ts>"
    out["provenance"] = prov
    return out


class QueryGoldenTests(unittest.TestCase):
    def test_query_golden_song(self) -> None:
        metadata = _Store(_load_fixture("metadata.json"))
        system = _System(metadata)
        out = run_query_without_state(system, "what song is playing")
        expected = _load_fixture("expected_song.json")
        self.assertEqual(_normalize_ts(out), expected)

    def test_query_golden_quorum(self) -> None:
        metadata = _Store(_load_fixture("metadata.json"))
        system = _System(metadata)
        out = run_query_without_state(system, "who is working with me on the quorum task")
        expected = _load_fixture("expected_quorum.json")
        self.assertEqual(_normalize_ts(out), expected)


if __name__ == "__main__":
    unittest.main()

