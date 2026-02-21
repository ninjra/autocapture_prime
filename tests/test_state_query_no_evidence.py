import unittest

from autocapture_nx.kernel.query import run_state_query
from autocapture_nx.state_layer.evidence_compiler import EvidenceCompiler
from autocapture_nx.state_layer.policy_gate import StatePolicyGate
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.answer_basic.plugin import AnswerBuilder


class _Parser:
    def parse(self, _text):
        return {"time_window": None}


class _Retrieval:
    def search(self, _query, **_kwargs):
        return []

    def trace(self):
        return []


class _System:
    def __init__(self, config, caps):
        self.config = config
        self._caps = caps

    def get(self, name):
        return self._caps[name]


class StateQueryNoEvidenceTests(unittest.TestCase):
    def test_no_evidence_response(self):
        config = {
            "processing": {"state_layer": {"query_enabled": True}},
            "promptops": {"enabled": False, "require_citations": True},
        }
        ctx = PluginContext(
            config=config,
            get_capability=lambda _name: None,
            logger=lambda *_args, **_kwargs: None,
            rng=None,
            rng_seed=None,
            rng_seed_hex=None,
        )
        evidence_compiler = EvidenceCompiler("test.compiler", ctx)
        policy_gate = StatePolicyGate(config)
        answer = AnswerBuilder("test.answer", ctx)
        system = _System(
            config,
            {
                "time.intent_parser": _Parser(),
                "state.retrieval": _Retrieval(),
                "state.evidence_compiler": evidence_compiler,
                "state.policy": policy_gate,
                "answer.builder": answer,
                "storage.metadata": {},
            },
        )
        result = run_state_query(system, "what happened")
        self.assertEqual(result["answer"]["state"], "no_evidence")


if __name__ == "__main__":
    unittest.main()
