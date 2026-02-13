import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.plugin_system.manager import PluginManager


class PluginUpdateRollbackTests(unittest.TestCase):
    def test_update_lock_entry_and_rollback_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_dir = Path(tmp) / "cfg"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            lockfile = cfg_dir / "plugin_locks.json"
            # Seed lockfile with a bogus entry so update produces a diff.
            lockfile.write_text(
                json.dumps({"plugins": {"builtin.ocr.basic": {"manifest_sha256": "0" * 64, "artifact_sha256": "0" * 64}}}, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            cfg = {
                "paths": {"config_dir": str(cfg_dir)},
                "plugins": {"locks": {"lockfile": str(lockfile), "enforce": False}},
            }
            mgr = PluginManager(cfg, safe_mode=False)
            result = mgr.update_lock_entry("builtin.ocr.basic", reason="test_update")
            self.assertTrue(result.get("ok"), result)
            diff = result.get("diff") or {}
            self.assertTrue(diff.get("ok"), diff)
            self.assertEqual(int(diff.get("changes_count") or 0), 1)

            pre = result.get("pre_snapshot") or {}
            pre_path = pre.get("snapshot")
            self.assertTrue(pre_path)

            # Rollback to the pre-update snapshot should restore the bogus hashes.
            rolled = mgr.lockfile_rollback(str(pre_path))
            self.assertTrue(rolled.get("ok"), rolled)
            restored = json.loads(lockfile.read_text(encoding="utf-8"))
            entry = restored.get("plugins", {}).get("builtin.ocr.basic", {})
            self.assertEqual(entry.get("manifest_sha256"), "0" * 64)
            self.assertEqual(entry.get("artifact_sha256"), "0" * 64)


if __name__ == "__main__":
    unittest.main()

