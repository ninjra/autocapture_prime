"""Retrieval signals and traces."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalTrace:
    tier: str
    reason: str
    result_count: int
