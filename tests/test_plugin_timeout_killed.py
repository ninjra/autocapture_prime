from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.errors import PluginTimeoutError
from autocapture_nx.plugin_system.host import SubprocessPlugin


class PluginTimeoutKilledTests(unittest.TestCase):
    def test_timeout_kills_subprocess_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            plugin_path = Path("tests/fixtures/plugins/timeout_plugin.py").resolve()

            # Keep runtime lightweight for WSL stability:
            # - tight RPC timeout
            # - tight memory limit
            cfg: dict = {
                "storage": {"data_dir": str(data_dir)},
                "plugins": {
                    "hosting": {
                        "rpc_timeout_s": 0.2,
                        "rpc_startup_timeout_s": 3,
                        "job_limits": {"max_memory_mb": 256, "max_processes": 1, "cpu_time_ms": 10_000},
                    }
                },
            }

            plugin = SubprocessPlugin(
                plugin_path,
                "create_plugin",
                "test.timeout_plugin",
                network_allowed=False,
                config=cfg,
                plugin_config=cfg,
                capabilities={},
                allowed_capabilities=None,
                filesystem_policy=None,
                entrypoint_kind="test.sleeper",
                provided_capabilities=["test.sleeper"],
                rng_enabled=False,
            )
            try:
                caps = plugin.capabilities()
                self.assertIn("test.sleeper", caps)
                with self.assertRaises(PluginTimeoutError):
                    # Exceeds rpc_timeout_s -> should force-close host process.
                    caps["test.sleeper"].sleep(1.0)
                # The SubprocessPlugin keeps the host wrapper object, but the
                # underlying process should be terminated.
                host = getattr(plugin, "_host", None)
                self.assertIsNotNone(host)
                proc = getattr(host, "_proc", None)
                self.assertTrue(proc is None or proc.poll() is not None, "process should be terminated on timeout")
            finally:
                try:
                    plugin.close()
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
