"""Append-only rules ledger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from autocapture.core.jsonschema import validate_schema
from autocapture.rules.schema import RULE_SCHEMA


class RulesLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def append(self, entry: dict[str, Any]) -> None:
        validate_schema(RULE_SCHEMA, entry)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    def iter_entries(self) -> Iterable[dict[str, Any]]:
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                yield json.loads(line)
