from __future__ import annotations


def _base_config() -> dict:
    return {
        "plugins": {"permissions": {"network_allowed_plugin_ids": ["mx.core.llm_openai_compat"]}},
        "privacy": {
            "egress": {
                "enabled": True,
                "approval_required": True,
                "default_sanitize": True,
                "destination_allowlist": ["https://api.openai.com"],
            },
            "cloud": {"enabled": False, "allow_images": False},
        },
    }


def test_policy_gate_blocks_cloud_by_default():
    from autocapture.plugins.policy_gate import PolicyGate

    class Sanitizer:
        def sanitize_payload(self, payload):
            out = dict(payload)
            out["schema_version"] = int(out.get("schema_version", 1) or 1)
            return out

        def leak_check(self, _payload):
            return True

    gate = PolicyGate(_base_config(), Sanitizer())
    decision = gate.enforce(
        "mx.core.llm_openai_compat",
        {"schema_version": 1, "messages": [{"role": "user", "content": "hi"}]},
        url="https://api.openai.com",
    )
    assert not decision.ok
    assert decision.reason == "cloud_disabled"

