import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.egress_gateway.plugin import EgressGateway


class _Sanitizer:
    def sanitize_payload(self, payload):
        return dict(payload)

    def leak_check(self, payload):
        return True

    def detokenize_payload(self, payload):
        return payload


class _EventBuilder:
    def __init__(self):
        self.entries = []

    def ledger_entry(self, stage, inputs, outputs, payload=None, **_kwargs):
        self.entries.append(payload or {})
        return payload.get("packet_hash") if isinstance(payload, dict) else None


class EgressLedgerTests(unittest.TestCase):
    def test_egress_packet_ledgered(self):
        config = {
            "gateway": {"openai_base_url": "http://example.com", "egress_path": "/v1/egress", "timeout_s": 1},
            "privacy": {
                "cloud": {"enabled": True, "allow_images": True},
                "egress": {
                    "enabled": True,
                    # Default policy is fail-closed with approval_required=true.
                    # This unit test verifies ledger emission, not approvals flow.
                    "approval_required": False,
                    "default_sanitize": True,
                    "allow_raw_egress": False,
                    "reasoning_packet_only": False,
                    "token_scope": "per_provider",
                    "token_format": "{token}",
                },
            },
            "plugins": {"permissions": {"network_allowed_plugin_ids": ["builtin.egress.gateway"]}},
        }
        sanitizer = _Sanitizer()
        builder = _EventBuilder()

        def get_capability(name):
            return {
                "privacy.egress_sanitizer": sanitizer,
                "event.builder": builder,
            }.get(name)

        plugin = EgressGateway(
            "builtin.egress.gateway",
            PluginContext(config=config, get_capability=get_capability, logger=lambda _m: None),
        )
        plugin._post_json = lambda _u, _p, _h, _t: (200, {"ok": True})
        payload = {"query": "hello", "facts": [], "constraints": {}, "intent": ""}
        plugin.send(payload)

        self.assertTrue(builder.entries)
        entry = builder.entries[-1]
        self.assertEqual(entry.get("event"), "egress.packet")
        self.assertTrue(entry.get("packet_hash"))
        self.assertEqual(entry.get("schema_version"), 1)


if __name__ == "__main__":
    unittest.main()
