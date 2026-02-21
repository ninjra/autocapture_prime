from __future__ import annotations


def _cfg(*, cloud_enabled: bool, egress_enabled: bool) -> dict:
    return {
        "plugins": {"permissions": {"network_allowed_plugin_ids": ["mx.core.llm_openai_compat"]}},
        "privacy": {
            "egress": {
                "enabled": bool(egress_enabled),
                "approval_required": True,
                "default_sanitize": True,
                "destination_allowlist": ["https://api.openai.com"],
            },
            "cloud": {"enabled": bool(cloud_enabled), "allow_images": False},
        },
    }


class _Sanitizer:
    def sanitize_payload(self, payload):
        out = dict(payload)
        out["schema_version"] = int(out.get("schema_version", 1) or 1)
        return out

    def leak_check(self, _payload):
        return True


def test_cloud_enabled_but_egress_disabled_blocks():
    from autocapture.plugins.policy_gate import PolicyGate

    gate = PolicyGate(_cfg(cloud_enabled=True, egress_enabled=False), _Sanitizer())
    decision = gate.enforce(
        "mx.core.llm_openai_compat",
        {"schema_version": 1, "messages": [{"role": "user", "content": "hi"}]},
        url="https://api.openai.com",
    )
    assert not decision.ok
    assert decision.reason == "egress_disabled"


def test_egress_enabled_but_cloud_disabled_blocks():
    from autocapture.plugins.policy_gate import PolicyGate

    gate = PolicyGate(_cfg(cloud_enabled=False, egress_enabled=True), _Sanitizer())
    decision = gate.enforce(
        "mx.core.llm_openai_compat",
        {"schema_version": 1, "messages": [{"role": "user", "content": "hi"}]},
        url="https://api.openai.com",
    )
    assert not decision.ok
    assert decision.reason == "cloud_disabled"


def test_cloud_and_egress_enabled_still_requires_approval():
    from autocapture.plugins.policy_gate import PolicyGate

    gate = PolicyGate(_cfg(cloud_enabled=True, egress_enabled=True), _Sanitizer())
    decision = gate.enforce(
        "mx.core.llm_openai_compat",
        {"schema_version": 1, "messages": [{"role": "user", "content": "hi"}]},
        url="https://api.openai.com",
    )
    assert not decision.ok
    assert decision.reason.startswith("approval_required")

