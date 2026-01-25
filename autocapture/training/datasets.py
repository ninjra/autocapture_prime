"""Dataset helpers for training pipelines."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from autocapture.core.hashing import hash_canonical


@dataclass(frozen=True)
class Dataset:
    name: str
    items: list[dict[str, Any]]
    dataset_hash: str


def _normalize_value(value: Any) -> Any:
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, dict):
        return {str(k): _normalize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value


def _normalize_items(items: Iterable[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            normalized.append(_normalize_value(item))
        else:
            normalized.append({"text": str(item)})
    return normalized


def load_dataset(path: str | Path, *, name: str | None = None) -> Dataset:
    path = Path(path)
    if path.suffix == ".jsonl":
        items = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                items.append(json.loads(line))
    else:
        items = json.loads(path.read_text(encoding="utf-8"))
    normalized = _normalize_items(items)
    return Dataset(name=name or path.stem, items=normalized, dataset_hash=hash_canonical(normalized))


def dataset_from_items(items: Iterable[Any], *, name: str = "dataset") -> Dataset:
    normalized = _normalize_items(items)
    return Dataset(name=name, items=normalized, dataset_hash=hash_canonical(normalized))
