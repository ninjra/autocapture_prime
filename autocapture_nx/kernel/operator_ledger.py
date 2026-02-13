"""Operator command ledgering (OPS-05).

Operator actions must be auditable and append-only. We record each operator
command as:
- a journal event
- a ledger entry (hash-chained)
"""

from __future__ import annotations

from typing import Any

from autocapture_nx.kernel.event_builder import EventBuilder
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.journal_basic.plugin import JournalWriter
from plugins.builtin.ledger_basic.plugin import LedgerWriter


def record_operator_action(
    *,
    config: dict[str, Any],
    action: str,
    payload: dict[str, Any] | None = None,
    entry_id: str | None = None,
) -> dict[str, Any]:
    payload = dict(payload or {})
    payload.setdefault("schema_version", 1)
    payload.setdefault("action", str(action))
    ctx = PluginContext(
        config=config,
        get_capability=lambda _name: None,
        logger=lambda _m: None,
        rng=None,
        rng_seed=None,
        rng_seed_hex=None,
    )
    journal = JournalWriter("builtin.journal.basic", ctx)
    ledger = LedgerWriter("builtin.ledger.basic", ctx)
    builder = EventBuilder(config, journal, ledger, anchor=None)
    event_id = builder.journal_event(f"operator.{action}", payload, event_id=entry_id)
    ledger_hash = builder.ledger_entry(
        f"operator.{action}",
        inputs=[],
        outputs=[],
        payload=payload,
        entry_id=entry_id,
    )
    return {"ok": True, "event_id": event_id, "ledger_hash": ledger_hash}
