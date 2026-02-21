"""Schema-backed I/O contracts for plugin capability calls."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.schema_registry import SchemaRegistry
from autocapture_nx.kernel.paths import resolve_repo_path


@dataclass(frozen=True)
class IOContract:
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None


_DEFAULT_CONTRACTS: dict[str, dict[str, dict[str, str]]] = {
    "processing.stage.hooks": {
        "run_stage": {
            "input_schema_path": "contracts/sst_stage_input.schema.json",
            "output_schema_path": "contracts/sst_stage_output.schema.json",
        }
    },
    "answer.builder": {
        "build": {
            "input_schema_path": "contracts/answer_build_input.schema.json",
            "output_schema_path": "contracts/answer_build_output.schema.json",
        }
    },
    "answer.synthesizer": {
        "synthesize": {
            "input_schema_path": "contracts/answer_synthesize_input.schema.json",
            "output_schema_path": "contracts/answer_synthesize_output.schema.json",
        }
    },
}


def _resolve_schema_path(raw: str, plugin_root: Path) -> Path:
    candidate = Path(str(raw))
    if candidate.is_absolute():
        return candidate
    plugin_candidate = plugin_root / candidate
    if plugin_candidate.exists():
        return plugin_candidate
    return resolve_repo_path(candidate)


def _load_schema(
    registry: SchemaRegistry,
    *,
    schema_value: Any,
    schema_path: str | None,
    plugin_root: Path,
) -> dict[str, Any] | None:
    if isinstance(schema_value, dict):
        return schema_value
    if schema_path:
        resolved = _resolve_schema_path(schema_path, plugin_root)
        return registry.load_schema_path(resolved)
    return None


def _load_contract_mapping(
    registry: SchemaRegistry,
    raw: dict[str, Any],
    *,
    plugin_root: Path,
) -> dict[str, dict[str, IOContract]]:
    resolved: dict[str, dict[str, IOContract]] = {}
    for capability, methods in raw.items():
        if not isinstance(methods, dict):
            continue
        for method, entry in methods.items():
            if not isinstance(entry, dict):
                continue
            input_schema = _load_schema(
                registry,
                schema_value=entry.get("input_schema"),
                schema_path=entry.get("input_schema_path"),
                plugin_root=plugin_root,
            )
            output_schema = _load_schema(
                registry,
                schema_value=entry.get("output_schema"),
                schema_path=entry.get("output_schema_path"),
                plugin_root=plugin_root,
            )
            resolved.setdefault(str(capability), {})[str(method)] = IOContract(
                input_schema=input_schema,
                output_schema=output_schema,
            )
    return resolved


def load_io_contracts(
    registry: SchemaRegistry,
    manifest: dict[str, Any],
    *,
    plugin_root: Path,
) -> dict[str, dict[str, IOContract]]:
    contracts: dict[str, dict[str, IOContract]] = {}
    defaults = _load_contract_mapping(registry, _DEFAULT_CONTRACTS, plugin_root=plugin_root)
    for capability, methods in defaults.items():
        contracts.setdefault(capability, {}).update(methods)

    raw = manifest.get("io_contracts", {})
    if isinstance(raw, dict) and raw:
        overrides = _load_contract_mapping(registry, raw, plugin_root=plugin_root)
        for capability, methods in overrides.items():
            contracts.setdefault(capability, {}).update(methods)
    return contracts
