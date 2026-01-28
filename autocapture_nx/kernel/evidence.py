"""Evidence record validation against contract schema."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from autocapture_nx.kernel.config import SchemaLiteValidator
from autocapture_nx.kernel.paths import resolve_repo_path


_validator = SchemaLiteValidator()


def is_evidence_like(record: dict[str, Any]) -> bool:
    record_type = str(record.get("record_type", ""))
    return record_type.startswith("evidence.") or record_type.startswith("derived.")


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    path = resolve_repo_path("contracts/evidence.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_evidence_record(record: dict[str, Any], record_id: str | None = None) -> None:
    if not is_evidence_like(record):
        return
    try:
        _validator.validate(_schema(), record)
    except Exception as exc:  # pragma: no cover - error handling exercised in tests
        suffix = f" {record_id}" if record_id else ""
        raise ValueError(f"Evidence record{suffix} invalid: {exc}") from exc
