"""Rules store rebuilt from ledger."""

from __future__ import annotations

from typing import Any

from autocapture.rules.ledger import RulesLedger


class RulesStore:
    def __init__(self, ledger: RulesLedger) -> None:
        self.ledger = ledger

    def rebuild_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {}
        for entry in self.ledger.iter_entries():
            action = entry.get("action")
            rule_id = entry.get("rule_id")
            payload = entry.get("payload", {})
            if action == "add":
                state[rule_id] = {"enabled": True, **payload}
            elif action == "disable" and rule_id in state:
                state[rule_id]["enabled"] = False
            elif action == "update" and rule_id in state:
                state[rule_id].update(payload)
        return state
