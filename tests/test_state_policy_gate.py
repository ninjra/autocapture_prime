import unittest

from autocapture_nx.state_layer.policy_gate import StatePolicyGate


class StatePolicyGateTests(unittest.TestCase):
    def test_policy_gate_exports_disabled(self) -> None:
        config = {
            "processing": {
                "state_layer": {
                    "policy": {
                        "allow_raw_media": False,
                        "allow_text_export": False,
                        "redact_text": True,
                        "app_allowlist": [],
                        "app_denylist": [],
                    }
                }
            }
        }
        gate = StatePolicyGate(config)
        decision = gate.decide()
        self.assertFalse(decision.can_show_raw_media)
        self.assertFalse(decision.can_export_text)
        self.assertTrue(decision.redact_text)

    def test_policy_gate_allowlist(self) -> None:
        config = {
            "processing": {
                "state_layer": {
                    "policy": {
                        "allow_raw_media": False,
                        "allow_text_export": True,
                        "redact_text": False,
                        "app_allowlist": ["notepad"],
                        "app_denylist": [],
                    }
                }
            }
        }
        gate = StatePolicyGate(config)
        decision = gate.decide()
        self.assertTrue(gate.app_allowed("notepad.exe", decision))
        self.assertFalse(gate.app_allowed("browser.exe", decision))


if __name__ == "__main__":
    unittest.main()
