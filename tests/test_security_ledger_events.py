import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths
from autocapture_nx.kernel.loader import Kernel


class SecurityLedgerEventTests(unittest.TestCase):
    def test_lock_and_config_changes_emit_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            run_state = {
                "run_id": "prev",
                "state": "stopped",
                "ts_utc": "2025-01-01T00:00:00Z",
                "locks": {"contracts": "old_contract", "plugins": "old_plugins"},
                "config_hash": "old_config",
            }
            (data_dir / "run_state.json").write_text(json.dumps(run_state), encoding="utf-8")

            paths = ConfigPaths(
                default_path=Path("config") / "default.json",
                user_path=root / "user.json",
                schema_path=Path("contracts") / "config_schema.json",
                backup_dir=root / "backup",
            )
            override = {"storage": {"data_dir": str(data_dir)}}
            paths.user_path.write_text(json.dumps(override), encoding="utf-8")

            kernel = Kernel(paths, safe_mode=False)
            system = kernel.boot(start_conductor=False)
            _ = system
            ledger_path = data_dir / "ledger.ndjson"
            events = []
            if ledger_path.exists():
                for line in ledger_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    events.append(entry.get("payload", {}).get("event"))
            kernel.shutdown()
            self.assertIn("lock_update", events)
            self.assertIn("config_change", events)


if __name__ == "__main__":
    unittest.main()
