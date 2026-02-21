"""Settings schema for UX."""

from __future__ import annotations


SETTINGS_SCHEMA = {
    "schema_version": 1,
    "tiers": [
        {"id": "basic", "label": "Basic"},
        {"id": "advanced", "label": "Advanced"},
    ],
    "sections": [
        {"id": "privacy", "label": "Privacy"},
        {"id": "performance", "label": "Performance"},
        {"id": "storage", "label": "Storage"},
    ],
}


def get_schema() -> dict:
    return SETTINGS_SCHEMA
