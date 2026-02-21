import json
import random
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths
from autocapture_nx.kernel.loader import Kernel


def _paths(tmp: str) -> ConfigPaths:
    root = Path(tmp)
    default_path = root / "default.json"
    schema_path = root / "schema.json"
    user_path = root / "user.json"
    backup_dir = root / "backup"
    with open("config/default.json", "r", encoding="utf-8") as handle:
        default = json.load(handle)
    with open(default_path, "w", encoding="utf-8") as handle:
        json.dump(default, handle, indent=2, sort_keys=True)
    with open("contracts/config_schema.json", "r", encoding="utf-8") as handle:
        schema = json.load(handle)
    with open(schema_path, "w", encoding="utf-8") as handle:
        json.dump(schema, handle, indent=2, sort_keys=True)
    user_override = {
        "paths": {"config_dir": str(root), "data_dir": str(root / "data")},
        "storage": {
            "data_dir": str(root / "data"),
            "spool_dir": str(root / "data" / "spool"),
            "crypto": {
                "keyring_path": str(root / "data" / "vault" / "keyring.json"),
                "root_key_path": str(root / "data" / "vault" / "root.key"),
            },
        },
        "plugins": {
            "enabled": {
                "builtin.capture.windows": False,
                "builtin.capture.audio.windows": False,
                "builtin.tracking.input.windows": False,
                "builtin.window.metadata.windows": False,
            }
        },
    }
    with open(user_path, "w", encoding="utf-8") as handle:
        json.dump(user_override, handle, indent=2, sort_keys=True)
    return ConfigPaths(default_path, user_path, schema_path, backup_dir)


class CrashRecoveryChaosTests(unittest.TestCase):
    def test_recovery_is_deterministic_under_tmp_and_partial_journal(self) -> None:
        # Deterministic chaos: generate a few variants of tmp + partial journal and
        # ensure boot completes and recovery archives tmp files without deletion.
        rng = random.Random(20260209)
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            data_dir = Path(tmp) / "data"
            spool_dir = data_dir / "spool"
            spool_dir.mkdir(parents=True, exist_ok=True)

            journal_path = data_dir / "journal.ndjson"
            for i in range(3):
                # Create a tmp artifact representing an interrupted write.
                tmp_name = f"segment_{i}_{rng.randint(0, 9999)}.tmp"
                (spool_dir / tmp_name).write_text("partial", encoding="utf-8")

                # Append a partial/corrupt journal line (simulated crash mid-write).
                journal_path.parent.mkdir(parents=True, exist_ok=True)
                with open(journal_path, "a", encoding="utf-8") as handle:
                    handle.write('{"event_type":"capture.stage","payload":{"record_id":"x"')  # missing braces/newline
                    handle.write("\n")

                kernel = Kernel(paths, safe_mode=False)
                kernel.boot(start_conductor=False)
                kernel.shutdown()

            # Recovery should have archived tmp files.
            archived_root = data_dir / "recovery" / "archived_tmp"
            self.assertTrue(archived_root.exists())
            archived = list(archived_root.rglob("*.tmp"))
            self.assertGreater(len(archived), 0)

            # Ensure ledger records recovery at least once.
            ledger_path = data_dir / "ledger.ndjson"
            self.assertTrue(ledger_path.exists())
            entries = [
                json.loads(line)
                for line in ledger_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and line.strip().startswith("{")
            ]
            events = [entry.get("payload", {}).get("event") for entry in entries if isinstance(entry, dict)]
            self.assertIn("storage.recovery", events)


if __name__ == "__main__":
    unittest.main()
