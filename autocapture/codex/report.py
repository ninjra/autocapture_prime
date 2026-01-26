"""Codex report formatting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class ValidatorReport:
    type: str
    ok: bool
    detail: str
    data: dict[str, Any]


@dataclass(frozen=True)
class RequirementReport:
    req_id: str
    title: str
    pillars: list[str]
    artifacts_ok: bool
    artifacts_missing: list[str]
    validators: list[ValidatorReport]

    @property
    def ok(self) -> bool:
        return self.artifacts_ok and all(v.ok for v in self.validators)


@dataclass(frozen=True)
class CodexReport:
    blueprint_id: str
    version: int
    generated_at: str
    requirements: list[RequirementReport]

    def summary(self) -> dict[str, Any]:
        total = len(self.requirements)
        passed = sum(1 for r in self.requirements if r.ok)
        failed = total - passed
        return {"total": total, "passed": passed, "failed": failed}

    def to_dict(self) -> dict[str, Any]:
        return {
            "blueprint_id": self.blueprint_id,
            "codex_spec_version": self.version,
            "generated_at": self.generated_at,
            "summary": self.summary(),
            "requirements": [
                {
                    "id": r.req_id,
                    "title": r.title,
                    "pillars": r.pillars,
                    "ok": r.ok,
                    "artifacts_ok": r.artifacts_ok,
                    "artifacts_missing": r.artifacts_missing,
                    "validators": [
                        {
                            "type": v.type,
                            "ok": v.ok,
                            "detail": v.detail,
                            "data": v.data,
                        }
                        for v in r.validators
                    ],
                }
                for r in self.requirements
            ],
        }


def build_report(blueprint_id: str, version: int, requirements: list[RequirementReport]) -> CodexReport:
    return CodexReport(
        blueprint_id=blueprint_id,
        version=version,
        generated_at=datetime.now(timezone.utc).isoformat(),
        requirements=requirements,
    )
