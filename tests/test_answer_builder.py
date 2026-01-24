import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.answer_basic.plugin import AnswerBuilder
from plugins.builtin.citation_basic.plugin import CitationValidator


class AnswerBuilderTests(unittest.TestCase):
    def test_build_with_citations(self):
        validator = CitationValidator("cit", PluginContext(config={}, get_capability=lambda _k: None, logger=lambda _m: None))
        def get_capability(name):
            if name == "citation.validator":
                return validator
            raise KeyError(name)
        ctx = PluginContext(config={}, get_capability=get_capability, logger=lambda _m: None)
        builder = AnswerBuilder("ans", ctx)
        claims = [{
            "text": "Example claim",
            "citations": [{"span_id": "s1", "source": "local", "offset_start": 0, "offset_end": 10}],
        }]
        result = builder.build(claims)
        self.assertEqual(result["claims"][0]["text"], "Example claim")


if __name__ == "__main__":
    unittest.main()
