import random
import unittest

from autocapture.config.validator import ValidationError, validate_config


class ConfigFuzzTests(unittest.TestCase):
    def test_config_validator_is_stable_under_mutations(self) -> None:
        base = {
            "schema_version": 1,
            "web": {"bind": "127.0.0.1", "port": 8787},
            "plugins": {"hosting": {"mode": "subprocess"}},
        }
        rng = random.Random(1337)
        # Deterministic corpus-ish mutations.
        for _ in range(200):
            cfg = dict(base)
            if rng.random() < 0.3:
                cfg["web"] = dict(cfg["web"])
                cfg["web"]["bind"] = rng.choice(["127.0.0.1", "::1", "0.0.0.0", "example.com", 123])
            if rng.random() < 0.3:
                cfg["plugins"] = dict(cfg.get("plugins", {}))
                cfg["plugins"]["hosting"] = {"mode": rng.choice(["subprocess", "inproc", None, 5])}
            try:
                validate_config(cfg)
            except ValidationError as exc:
                # Deterministic error codes: no crashes, always has a code.
                self.assertTrue(exc.code)


if __name__ == "__main__":
    unittest.main()

