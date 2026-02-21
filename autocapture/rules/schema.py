"""Rules schema."""

from __future__ import annotations

RULE_SCHEMA = {
    "type": "object",
    "required": ["rule_id", "action", "payload", "ts_utc"],
    "properties": {
        "rule_id": {"type": "string"},
        "action": {"type": "string"},
        "payload": {"type": "object"},
        "ts_utc": {"type": "string"},
    },
    "additionalProperties": True,
}
