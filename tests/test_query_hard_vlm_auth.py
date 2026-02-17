import os
import unittest
from types import SimpleNamespace
from unittest import mock

from autocapture_nx.kernel import query as query_mod


class QueryHardVlmAuthTests(unittest.TestCase):
    def test_hard_vlm_api_key_prefers_env(self) -> None:
        system = SimpleNamespace(
            config={
                "plugins": {
                    "settings": {
                        "builtin.vlm.vllm_localhost": {"api_key": "config-key"},
                    }
                }
            }
        )
        with mock.patch.dict(os.environ, {"AUTOCAPTURE_VLM_API_KEY": "env-key"}, clear=False):
            self.assertEqual(query_mod._hard_vlm_api_key(system), "env-key")

    def test_hard_vlm_api_key_uses_plugin_settings_fallback(self) -> None:
        system = SimpleNamespace(
            config={
                "plugins": {
                    "settings": {
                        "builtin.vlm.vllm_localhost": {"api_key": "vlm-key"},
                    }
                }
            }
        )
        with mock.patch.dict(os.environ, {"AUTOCAPTURE_VLM_API_KEY": ""}, clear=False):
            self.assertEqual(query_mod._hard_vlm_api_key(system), "vlm-key")

    def test_hard_vlm_api_key_uses_answer_synth_fallback(self) -> None:
        system = SimpleNamespace(
            config={
                "plugins": {
                    "settings": {
                        "builtin.answer.synth_vllm_localhost": {"api_key": "synth-key"},
                    }
                }
            }
        )
        with mock.patch.dict(os.environ, {"AUTOCAPTURE_VLM_API_KEY": ""}, clear=False):
            self.assertEqual(query_mod._hard_vlm_api_key(system), "synth-key")


if __name__ == "__main__":
    unittest.main()
