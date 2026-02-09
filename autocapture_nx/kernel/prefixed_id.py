"""Deterministic prefixed IDs (content-addressed when possible).

FND-05: ingest boundary uses sha256(content) -> stable input_id.
This module exists as a stable import surface (vs. re-exporting from ids.py).
"""

from __future__ import annotations

import re

from autocapture_nx.kernel.ids import prefixed_id as _prefixed_id


_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def prefixed_id(run_id: str, kind: str, seq: int) -> str:
    return _prefixed_id(run_id, kind, seq)


def input_id_from_sha256(sha256_hex: str) -> str:
    h = str(sha256_hex or "").strip().lower()
    if not _HEX_RE.match(h):
        raise ValueError("invalid_sha256_hex")
    # Use full hash for stable identity across machines/exports.
    return f"in_sha256_{h}"
