"""Runtime governor (NX import path).

This module intentionally re-exports the production governor implementation so
traceability and validators can reference a stable NX location.
"""

from __future__ import annotations

from autocapture.runtime.governor import (  # noqa: F401
    BudgetLease,
    BudgetSnapshot,
    GovernorDecision,
    RuntimeGovernor,
)

