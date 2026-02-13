from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tools.gate_vuln import _load_ignored_vuln_ids


def test_load_ignored_vuln_ids_missing_file(tmp_path: Path) -> None:
    ids, errors = _load_ignored_vuln_ids(tmp_path / "missing.json")
    assert ids == []
    assert errors == []


def test_load_ignored_vuln_ids_valid_future_entry(tmp_path: Path) -> None:
    allow = tmp_path / "vuln_allowlist.json"
    allow.write_text(
        json.dumps(
            {
                "ignored_ids": [
                    {
                        "id": "CVE-2025-69872",
                        "expires_utc": "2099-01-01T00:00:00Z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    ids, errors = _load_ignored_vuln_ids(allow, now=datetime(2026, 2, 13, tzinfo=timezone.utc))
    assert ids == ["CVE-2025-69872"]
    assert errors == []


def test_load_ignored_vuln_ids_expired_entry_fails(tmp_path: Path) -> None:
    allow = tmp_path / "vuln_allowlist.json"
    allow.write_text(
        json.dumps(
            {
                "ignored_ids": [
                    {
                        "id": "CVE-2000-0001",
                        "expires_utc": "2001-01-01T00:00:00Z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    ids, errors = _load_ignored_vuln_ids(allow, now=datetime(2026, 2, 13, tzinfo=timezone.utc))
    assert ids == []
    assert errors == ["expired:CVE-2000-0001"]
