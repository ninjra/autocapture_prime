import unittest


def _cfg_with_spawn_cap(cap: int) -> dict:
    return {"plugins": {"hosting": {"subprocess_spawn_concurrency": cap}}}


class SubprocessSpawnConcurrencyCapTests(unittest.TestCase):
    def test_spawn_concurrency_cap_blocks_second_spawn(self) -> None:
        from autocapture_nx.kernel.errors import PluginTimeoutError
        from autocapture_nx.plugin_system import host as host_mod

        # Ensure a clean slate for the module-global counter.
        host_mod._SUBPROCESS_SPAWN_ACTIVE = 0

        host_mod._acquire_spawn_slot(config=_cfg_with_spawn_cap(1), wait_timeout_s=0.0)
        try:
            with self.assertRaises(PluginTimeoutError):
                host_mod._acquire_spawn_slot(config=_cfg_with_spawn_cap(1), wait_timeout_s=0.0)
        finally:
            host_mod._release_spawn_slot()

        # After release, the next acquisition should succeed.
        host_mod._acquire_spawn_slot(config=_cfg_with_spawn_cap(1), wait_timeout_s=0.0)
        host_mod._release_spawn_slot()
