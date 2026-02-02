import unittest

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.workflow_miner import WorkflowMiner


def _span(state_id: str, ts_ms: int, model_version: str = "v1"):
    return {
        "state_id": state_id,
        "ts_start_ms": ts_ms,
        "provenance": {
            "model_version": model_version,
        },
    }


class WorkflowMinerTests(unittest.TestCase):
    def _miner(self):
        ctx = PluginContext(
            config={"processing": {"state_layer": {"builder": {}}}},
            get_capability=lambda _name: None,
            logger=lambda *_args, **_kwargs: None,
            rng=None,
            rng_seed=None,
            rng_seed_hex=None,
        )
        return WorkflowMiner("test.workflow", ctx)

    def test_miner_is_deterministic(self):
        miner = self._miner()
        spans = [
            _span("a", 0),
            _span("b", 1),
            _span("c", 2),
            _span("a", 3),
            _span("b", 4),
            _span("c", 5),
        ]
        state_tape = {"session_id": "run", "spans": spans, "edges": []}
        first = miner.mine(state_tape)
        second = miner.mine(state_tape)
        self.assertEqual(first, second)
        self.assertTrue(any(item.get("span_ids") == ["a", "b", "c"] for item in first))

    def test_seed_changes_workflow_id(self):
        miner = self._miner()
        spans = [
            _span("a", 0),
            _span("b", 1),
            _span("a", 2),
            _span("b", 3),
        ]
        base = {"session_id": "run", "spans": spans, "edges": []}
        wf_a = miner.mine({**base, "seed": "seed-a"})
        wf_b = miner.mine({**base, "seed": "seed-b"})
        if wf_a and wf_b:
            self.assertNotEqual(wf_a[0]["workflow_id"], wf_b[0]["workflow_id"])


if __name__ == "__main__":
    unittest.main()
