"""Codex spec loader for MX requirements."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ValidatorSpec:
    type: str
    config: dict[str, Any]


@dataclass(frozen=True)
class RequirementSpec:
    req_id: str
    title: str
    pillars: list[str]
    artifacts: list[str]
    validators: list[ValidatorSpec]


@dataclass(frozen=True)
class CodexSpec:
    blueprint_id: str
    version: int
    requirements: list[RequirementSpec]


DEFAULT_SPEC_PATH = Path("docs/spec/autocapture_mx_spec.yaml")


def load_spec(path: Path | None = None) -> CodexSpec:
    spec_path = path or DEFAULT_SPEC_PATH
    data = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    version = int(data.get("codex_spec_version", 0))
    blueprint_id = str(data.get("blueprint_id", ""))
    requirements: list[RequirementSpec] = []
    for item in data.get("requirements", []):
        validators = [
            ValidatorSpec(type=v.get("type", ""), config={k: v for k, v in v.items() if k != "type"})
            for v in item.get("validators", [])
        ]
        requirements.append(
            RequirementSpec(
                req_id=str(item.get("id", "")),
                title=str(item.get("title", "")),
                pillars=list(item.get("pillars", []) or []),
                artifacts=list(item.get("artifacts", []) or []),
                validators=validators,
            )
        )
    return CodexSpec(blueprint_id=blueprint_id, version=version, requirements=requirements)
