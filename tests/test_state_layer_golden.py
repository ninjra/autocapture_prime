import unittest

from autocapture_nx.kernel.config import load_config
from autocapture_nx.kernel.loader import default_config_paths
from autocapture_nx.state_layer.harness import load_state_eval_cases, run_state_eval


class StateLayerGoldenTests(unittest.TestCase):
    def test_state_layer_golden_eval(self) -> None:
        config = load_config(default_config_paths(), safe_mode=True)
        payload = load_state_eval_cases("tests/fixtures/state_golden.json")
        result = run_state_eval(config, cases=payload["cases"], states=payload["states"])
        self.assertTrue(result.get("ok"), msg=result)


if __name__ == "__main__":
    unittest.main()
