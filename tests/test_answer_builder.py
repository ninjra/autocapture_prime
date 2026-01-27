import unittest

from autocapture.core.hashing import hash_text, normalize_text
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.answer_basic.plugin import AnswerBuilder
from plugins.builtin.citation_basic.plugin import CitationValidator


class AnswerBuilderTests(unittest.TestCase):
    def test_build_with_citations(self):
        class _MetaStore:
            def __init__(self) -> None:
                self._data: dict[str, dict] = {}

            def put(self, record_id: str, value: dict) -> None:
                self._data[record_id] = value

            def get(self, record_id: str, default=None):
                return self._data.get(record_id, default)

        store = _MetaStore()
        evidence_text = "evidence"
        evidence_hash = hash_text(normalize_text(evidence_text))
        derived_text = "claim text"
        derived_hash = hash_text(normalize_text(derived_text))
        store.put("run1/segment/0", {"record_type": "evidence.capture.segment", "content_hash": evidence_hash})
        store.put(
            "run1/derived/0",
            {"record_type": "derived.text.ocr", "content_hash": derived_hash, "source_id": "run1/segment/0"},
        )

        def get_meta(name: str):
            if name == "storage.metadata":
                return store
            raise KeyError(name)

        validator = CitationValidator("cit", PluginContext(config={}, get_capability=get_meta, logger=lambda _m: None))
        def get_capability(name):
            if name == "citation.validator":
                return validator
            raise KeyError(name)
        ctx = PluginContext(config={}, get_capability=get_capability, logger=lambda _m: None)
        builder = AnswerBuilder("ans", ctx)
        claims = [{
            "text": "Example claim",
            "citations": [
                {
                    "span_id": "run1/segment/0",
                    "evidence_id": "run1/segment/0",
                    "evidence_hash": evidence_hash,
                    "derived_id": "run1/derived/0",
                    "derived_hash": derived_hash,
                    "source": "local",
                    "offset_start": 0,
                    "offset_end": 10,
                }
            ],
        }]
        result = builder.build(claims)
        self.assertEqual(result["state"], "ok")
        self.assertEqual(result["claims"][0]["text"], "Example claim")


if __name__ == "__main__":
    unittest.main()
