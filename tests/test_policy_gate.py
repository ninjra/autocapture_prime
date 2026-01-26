import unittest

from autocapture.plugins.policy_gate import PolicyGate


class _Sanitizer:
    def sanitize_payload(self, payload):
        return {"sanitized": True, **payload}

    def leak_check(self, payload):
        return True


class PolicyGateTests(unittest.TestCase):
    def _base_config(self):
        return {
            "plugins": {"permissions": {"network_allowed_plugin_ids": ["mx.gateway"]}},
            "privacy": {
                "cloud": {"enabled": True, "allow_images": False},
                "egress": {"default_sanitize": True, "allow_raw_egress": False},
            },
        }

    def test_blocks_when_cloud_disabled(self):
        cfg = self._base_config()
        cfg["privacy"]["cloud"]["enabled"] = False
        gate = PolicyGate(cfg, _Sanitizer())
        decision = gate.enforce("mx.gateway", {"q": "x"})
        self.assertFalse(decision.ok)
        self.assertEqual(decision.reason, "cloud_disabled")

    def test_blocks_raw_egress(self):
        cfg = self._base_config()
        gate = PolicyGate(cfg, _Sanitizer())
        decision = gate.enforce("mx.gateway", {"q": "x"}, allow_raw_egress=True)
        self.assertFalse(decision.ok)
        self.assertEqual(decision.reason, "raw_egress_blocked")

    def test_sanitized_allowed(self):
        cfg = self._base_config()
        gate = PolicyGate(cfg, _Sanitizer())
        decision = gate.enforce("mx.gateway", {"q": "x"})
        self.assertTrue(decision.ok)
        self.assertEqual(decision.reason, "sanitized")
        self.assertIsNotNone(decision.sanitized_payload)
        self.assertTrue(decision.sanitized_payload.get("sanitized"))


if __name__ == "__main__":
    unittest.main()
