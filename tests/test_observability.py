import os
import tempfile
import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.observability_basic.plugin import ObservabilityLogger


class ObservabilityTests(unittest.TestCase):
    def test_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "storage": {"data_dir": tmp},
                "observability": {"allow_evidence": False, "allowlist_keys": ["event", "message"]},
            }
            ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
            logger = ObservabilityLogger("obs", ctx)
            logger.log("test", {"message": "ok", "secret": "value"})
            log_path = os.path.join(tmp, "logs", "observability.log")
            with open(log_path, "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("<redacted>", content)
            self.assertNotIn("value", content)


if __name__ == "__main__":
    unittest.main()
