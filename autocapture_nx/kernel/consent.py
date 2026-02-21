"""Consent gating for capture.

This is intentionally simple and portable:
- Stored as an atomic JSON file under data_dir.
- Append-only audit/ledger events record changes (handled by callers).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.atomic_write import atomic_write_json


CONSENT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CaptureConsent:
    schema_version: int
    accepted: bool
    accepted_ts_utc: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def consent_path(*, data_dir: str | Path) -> Path:
    data_dir = Path(data_dir)
    return data_dir / "state" / "consent.capture.json"


def load_capture_consent(*, data_dir: str | Path) -> CaptureConsent:
    path = consent_path(data_dir=data_dir)
    if not path.exists():
        return CaptureConsent(schema_version=CONSENT_SCHEMA_VERSION, accepted=False, accepted_ts_utc=None)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        # Fail closed: malformed consent file disables capture until re-accepted.
        return CaptureConsent(schema_version=CONSENT_SCHEMA_VERSION, accepted=False, accepted_ts_utc=None)
    accepted = bool(payload.get("accepted", False))
    accepted_ts = payload.get("accepted_ts_utc")
    accepted_ts_utc = str(accepted_ts) if accepted_ts else None
    return CaptureConsent(schema_version=CONSENT_SCHEMA_VERSION, accepted=accepted, accepted_ts_utc=accepted_ts_utc)


def accept_capture_consent(*, data_dir: str | Path) -> CaptureConsent:
    path = consent_path(data_dir=data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    consent = CaptureConsent(schema_version=CONSENT_SCHEMA_VERSION, accepted=True, accepted_ts_utc=_utc_now())
    atomic_write_json(path, consent.to_dict(), indent=2, sort_keys=True)
    return consent

