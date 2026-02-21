import unittest

from autocapture_nx.kernel.system import System
from autocapture_nx.plugin_system.registry import CapabilityRegistry, LoadedPlugin


class _Closeable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class SystemCloseTests(unittest.TestCase):
    def test_system_close_calls_plugin_close_and_clears_caps(self) -> None:
        closeable = _Closeable()
        plugins = [LoadedPlugin(plugin_id="p1", manifest={}, instance=closeable, capabilities={})]
        caps = CapabilityRegistry()
        caps.register("dummy.cap", object(), network_allowed=False)
        system = System(config={}, plugins=plugins, capabilities=caps)

        system.close()

        self.assertTrue(closeable.closed)
        self.assertEqual(system.plugins, [])
        self.assertEqual(system.capabilities.all(), {})


if __name__ == "__main__":
    unittest.main()

