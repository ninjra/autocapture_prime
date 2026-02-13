import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.audit import PluginAuditLog
from autocapture_nx.plugin_system.registry import PluginRegistry


class PluginCrashLoopQuarantineTests(unittest.TestCase):
    def test_repeated_failures_auto_quarantine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_dir = Path(tmp) / "cfg"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            audit_path = Path(tmp) / "audit.db"
            plugin_id = "builtin.ocr.basic"
            config = {
                "paths": {"config_dir": str(cfg_dir)},
                "plugins": {
                    "allowlist": [plugin_id],
                    "enabled": {plugin_id: True},
                    "hosting": {"mode": "inproc", "inproc_allow_all": True, "wsl_force_inproc": False},
                    "locks": {"enforce": False},
                    "health": {"auto_quarantine": True, "crash_loop_failures": 3, "crash_loop_window_s": 300},
                },
                "storage": {"audit_db_path": str(audit_path)},
            }
            audit = PluginAuditLog.from_config(config)
            # Record three failures inside the window.
            for _i in range(3):
                audit.record(
                    run_id="run",
                    plugin_id=plugin_id,
                    capability="test.cap",
                    method="call",
                    ok=False,
                    error="boom",
                    duration_ms=1,
                    rows_read=0,
                    rows_written=0,
                    memory_rss_mb=0,
                    memory_vms_mb=0,
                    input_hash=None,
                    output_hash=None,
                    data_hash=None,
                    code_hash=None,
                    settings_hash=None,
                    input_bytes=0,
                    output_bytes=0,
                )

            reg = PluginRegistry(config, safe_mode=False)
            _loaded, _caps = reg.load_plugins()

            user_path = cfg_dir / "user.json"
            self.assertTrue(user_path.exists())
            user_cfg = json.loads(user_path.read_text(encoding="utf-8"))
            quarantine = user_cfg.get("plugins", {}).get("quarantine", {})
            self.assertIn(plugin_id, quarantine)
            self.assertEqual(quarantine[plugin_id].get("reason"), "crash_loop")


if __name__ == "__main__":
    unittest.main()

