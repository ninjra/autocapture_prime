import json
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import validate_config
from autocapture_nx.kernel.paths import resolve_repo_path
from autocapture_nx.kernel.errors import ConfigError


class LocalhostBindingTests(unittest.TestCase):
    def test_bind_host_must_be_loopback(self) -> None:
        cfg = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
        cfg["web"]["bind_host"] = "0.0.0.0"
        schema_path = resolve_repo_path("contracts/config_schema.json")
        with self.assertRaises(ConfigError):
            validate_config(schema_path, cfg)


if __name__ == "__main__":
    unittest.main()
