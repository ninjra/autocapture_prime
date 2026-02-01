import random
import unittest

from autocapture_nx.kernel.rng import RNGScope, RNGService, install_rng_guard


class RNGGuardTests(unittest.TestCase):
    def test_rng_service_deterministic(self):
        service = RNGService(
            enabled=True,
            strict=True,
            base_seed="seed",
            run_id="run",
            use_run_id=True,
        )
        seed_a = service.seed_for_plugin("plugin.a").plugin_seed
        seed_b = service.seed_for_plugin("plugin.a").plugin_seed
        seed_c = service.seed_for_plugin("plugin.b").plugin_seed
        self.assertEqual(seed_a, seed_b)
        self.assertNotEqual(seed_a, seed_c)

    def test_rng_scope_repeatable(self):
        install_rng_guard()
        with RNGScope(123, strict=True, enabled=True):
            vals1 = [random.random() for _ in range(3)]
        with RNGScope(123, strict=True, enabled=True):
            vals2 = [random.random() for _ in range(3)]
        self.assertEqual(vals1, vals2)


if __name__ == "__main__":
    unittest.main()
