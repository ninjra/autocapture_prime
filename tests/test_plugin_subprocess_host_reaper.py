import os
import types
import unittest
from pathlib import Path
import time

from autocapture_nx.plugin_system.host import SubprocessPlugin, reap_subprocess_hosts


class _FakeHost:
    def __init__(self, pid: int) -> None:
        self._proc = types.SimpleNamespace(pid=pid)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class PluginSubprocessHostReaperTests(unittest.TestCase):
    def test_reaper_enforces_global_cap_on_idle_hosts(self) -> None:
        prev_env = dict(os.environ)
        try:
            os.environ["AUTOCAPTURE_PLUGINS_LAZY_START"] = "1"
            os.environ["AUTOCAPTURE_PLUGINS_SUBPROCESS_MAX_HOSTS"] = "1"
            os.environ["AUTOCAPTURE_PLUGINS_SUBPROCESS_IDLE_TTL_S"] = "3600"

            cfg = {"plugins": {"hosting": {"mode": "subprocess"}}}
            fake_path = Path(__file__)

            p1 = SubprocessPlugin(
                plugin_path=fake_path,  # unused due to lazy-start seeding
                callable_name="noop",
                plugin_id="test.plugin.1",
                network_allowed=False,
                config=cfg,
                plugin_config=cfg,
                capabilities=None,
                allowed_capabilities=None,
                filesystem_policy=None,
                entrypoint_kind="prompt.bundle",
                provided_capabilities=["prompt.bundle"],
            )
            p2 = SubprocessPlugin(
                plugin_path=fake_path,
                callable_name="noop",
                plugin_id="test.plugin.2",
                network_allowed=False,
                config=cfg,
                plugin_config=cfg,
                capabilities=None,
                allowed_capabilities=None,
                filesystem_policy=None,
                entrypoint_kind="prompt.bundle",
                provided_capabilities=["prompt.bundle"],
            )
            p3 = SubprocessPlugin(
                plugin_path=fake_path,
                callable_name="noop",
                plugin_id="test.plugin.3",
                network_allowed=False,
                config=cfg,
                plugin_config=cfg,
                capabilities=None,
                allowed_capabilities=None,
                filesystem_policy=None,
                entrypoint_kind="prompt.bundle",
                provided_capabilities=["prompt.bundle"],
            )

            now = time.monotonic() + 5.0
            p1._host = _FakeHost(101)  # type: ignore[attr-defined]
            p2._host = _FakeHost(102)  # type: ignore[attr-defined]
            p3._host = _FakeHost(103)  # type: ignore[attr-defined]
            p1._last_used_mono = now - 30  # type: ignore[attr-defined]
            p2._last_used_mono = now - 20  # type: ignore[attr-defined]
            p3._last_used_mono = now - 10  # type: ignore[attr-defined]
            p1._in_flight = 0  # type: ignore[attr-defined]
            p2._in_flight = 0  # type: ignore[attr-defined]
            p3._in_flight = 0  # type: ignore[attr-defined]

            stats = reap_subprocess_hosts(force=False, now_mono=now)
            self.assertGreaterEqual(stats.get("closed_cap", 0), 2)
            self.assertEqual(stats.get("remaining"), 1)
        finally:
            os.environ.clear()
            os.environ.update(prev_env)


if __name__ == "__main__":
    unittest.main()
