import random
import unittest

from autocapture.config.validator import ValidationError, validate_plugin_manifest


class PluginManifestFuzzTests(unittest.TestCase):
    def test_plugin_manifest_validator_is_stable_under_mutations(self) -> None:
        base = {
            "plugin_id": "builtin.example",
            "entrypoint": "plugin.py:create_plugin",
            "permissions": {"network": False, "filesystem": {"read": [], "write": []}},
            "compat": {"requires_kernel": ">=0.0.0"},
        }
        rng = random.Random(20260209)
        for _ in range(200):
            m = dict(base)
            if rng.random() < 0.4:
                m["plugin_id"] = rng.choice(["builtin.example", "", None, 123])
            if rng.random() < 0.3:
                m["permissions"] = rng.choice([{}, {"network": True}, {"filesystem": {"read": ["./"]}}])
            try:
                validate_plugin_manifest(m)
            except ValidationError as exc:
                self.assertTrue(exc.code)


if __name__ == "__main__":
    unittest.main()

