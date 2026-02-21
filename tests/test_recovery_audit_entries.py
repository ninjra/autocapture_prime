from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.event_builder import EventBuilder
from autocapture_nx.kernel.config import ConfigPaths
from autocapture_nx.kernel.loader import Kernel


class _Journal:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def append_event(
        self,
        event_type: str,
        payload: dict,
        *,
        event_id: str | None = None,
        ts_utc: str | None = None,
        tzid: str | None = None,
        offset_minutes: int | None = None,
    ) -> str:
        self.events.append(
            {
                "event_type": str(event_type),
                "payload": dict(payload),
                "event_id": event_id,
                "ts_utc": ts_utc,
                "tzid": tzid,
                "offset_minutes": offset_minutes,
            }
        )
        return "journal_hash"


class _Ledger:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def append(self, entry: dict) -> str:
        self.entries.append(dict(entry))
        return "ledger_hash"


class _Anchor:
    def anchor(self, _ledger_hash: str) -> str:
        return "anchor_id"


class RecoveryAuditTests(unittest.TestCase):
    def test_recovery_archives_tmp_files_and_ledgered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            spool_dir = data_dir / "spool"
            spool_dir.mkdir(parents=True, exist_ok=True)

            tmp_file = spool_dir / "dangling.tmp"
            tmp_file.write_text("hello", encoding="utf-8")

            cfg = {"storage": {"data_dir": str(data_dir), "spool_dir": str(spool_dir)}}
            default_path = root / "default.json"
            user_path = root / "user.json"
            schema_path = root / "schema.json"
            default_path.write_text("{}", encoding="utf-8")
            user_path.write_text("{}", encoding="utf-8")
            schema_path.write_text("{}", encoding="utf-8")
            kernel = Kernel(
                ConfigPaths(
                    default_path=default_path,
                    user_path=user_path,
                    schema_path=schema_path,
                    backup_dir=(root / "backup").resolve(),
                )
            )
            kernel.config = cfg
            journal = _Journal()
            ledger = _Ledger()
            builder = EventBuilder(cfg, journal, ledger, _Anchor())

            kernel._run_recovery(builder, capabilities=None)

            self.assertFalse(tmp_file.exists(), "tmp file should have been archived, not left in place")
            archived = list((data_dir / "recovery" / "archived_tmp").rglob("dangling.tmp"))
            self.assertTrue(archived, "archived tmp file should exist under recovery/archived_tmp")

            recovery_events = [e for e in journal.events if isinstance(e, dict) and e.get("event_type") == "storage.recovery"]
            self.assertTrue(recovery_events, "recovery must write a storage.recovery journal event")
            last = recovery_events[-1]
            payload = last.get("payload") if isinstance(last.get("payload"), dict) else {}
            self.assertIn("archived_tmp_count", payload)
            self.assertGreaterEqual(int(payload.get("archived_tmp_count") or 0), 1)

            ledger_payloads = [e.get("payload") for e in ledger.entries if isinstance(e, dict)]
            self.assertTrue(any(isinstance(p, dict) and p.get("event") == "storage.recovery" for p in ledger_payloads))


if __name__ == "__main__":
    unittest.main()
