import unittest

from autocapture_nx.kernel.system import System
from autocapture_nx.plugin_system.registry import CapabilityRegistry


class SystemContainerTests(unittest.TestCase):
    def test_register_and_has(self) -> None:
        caps = CapabilityRegistry()
        system = System(config={}, plugins=[], capabilities=caps)
        self.assertFalse(system.has("test.cap"))
        system.register("test.cap", 123)
        self.assertTrue(system.has("test.cap"))
        cap = system.get("test.cap")
        self.assertEqual(getattr(cap, "_target", None), 123)


if __name__ == "__main__":
    unittest.main()
