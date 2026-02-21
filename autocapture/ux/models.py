"""UX models for API responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class DoctorCheck:
    name: str
    ok: bool
    detail: str


@dataclass
class DoctorReport:
    ok: bool
    generated_at_utc: str
    checks: list[DoctorCheck]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "generated_at_utc": self.generated_at_utc,
            "checks": [check.__dict__ for check in self.checks],
        }
