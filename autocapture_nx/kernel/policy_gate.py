"""Kernel policy helpers (compat shim for traceability).

The adversarial redesign doc references this module for META-06 evidence paths.
The actual implementation lives in `autocapture_nx/kernel/policy_snapshot.py`.

Keep this file lightweight: it re-exports the snapshot functions so the kernel
can persist content-addressed policy snapshots for citeable proof bundles.
"""

from __future__ import annotations

from autocapture_nx.kernel.policy_snapshot import (  # noqa: F401
    PolicySnapshotPersistResult,
    persist_policy_snapshot,
    policy_snapshot_hash,
    policy_snapshot_payload,
    policy_snapshot_record_id,
)

