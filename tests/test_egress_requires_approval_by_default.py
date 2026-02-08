from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autocapture.plugins.policy_gate import PolicyGate


class _Sanitizer:
    def sanitize_payload(self, payload: dict) -> dict:
        # Deterministic "sanitization" for tests.
        return dict(payload)

    def leak_check(self, _payload: dict) -> bool:
        return True


class _Ledger:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def append(self, entry: dict) -> str:
        self.entries.append(dict(entry))
        return "h"


class _Journal:
    def append_event(self, *_a, **_k) -> str:
        return "j"


class _Anchor:
    def anchor(self, _h: str) -> str:
        return "a"


class _Builder:
    def __init__(self) -> None:
        self._ledger = _Ledger()

    def ledger_entry(self, stage: str, inputs: list[str], outputs: list[str], *, payload: dict, **_k) -> str:
        entry = {"stage": stage, "payload": dict(payload), "inputs": list(inputs), "outputs": list(outputs)}
        self._ledger.append(entry)
        return "h"

    @property
    def ledger(self) -> _Ledger:
        return self._ledger


class EgressApprovalDefaultTests(unittest.TestCase):
    def test_egress_blocks_without_approval_then_allows_after_approve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            cfg = {
                "storage": {"data_dir": str(data_dir)},
                "plugins": {"permissions": {"network_allowed_plugin_ids": ["mx.core.llm_openai_compat"]}},
                "privacy": {
                    "cloud": {"enabled": True, "allow_images": False},
                    "egress": {
                        "enabled": True,
                        "default_sanitize": True,
                        "allow_raw_egress": False,
                        "approval_required": True,
                        "approval_store_path": str(data_dir / "egress" / "approvals.json"),
                        "destination_allowlist": ["example.com"],
                        "policy_id": "policy_test",
                    },
                },
            }
            builder = _Builder()
            gate = PolicyGate(cfg, _Sanitizer(), event_builder=builder)
            payload = {"schema_version": 1, "query": "hello"}

            decision0 = gate.enforce("mx.core.llm_openai_compat", payload, url="https://example.com/v1/chat/completions")
            self.assertFalse(decision0.ok)
            self.assertIn("approval_required", str(decision0.reason))

            store = getattr(gate, "_approval_store", None)
            self.assertIsNotNone(store)
            pending = store.list_requests()
            self.assertTrue(pending)
            approval_id = pending[0]["approval_id"]
            token = store.approve(approval_id)["token"]

            payload2 = dict(payload)
            payload2["approval_token"] = token
            decision = gate.enforce("mx.core.llm_openai_compat", payload2, url="https://example.com/v1/chat/completions")
            self.assertTrue(decision.ok)

            # Ledger should contain approval request + grant events via the store.
            events = [e.get("payload", {}).get("event") for e in builder.ledger.entries if isinstance(e, dict)]
            self.assertIn("egress.approval.request", events)
            self.assertIn("egress.approval.granted", events)


if __name__ == "__main__":
    unittest.main()
