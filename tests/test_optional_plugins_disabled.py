import json
import unittest
from pathlib import Path


class OptionalPluginsDisabledTests(unittest.TestCase):
    def test_optional_plugins_disabled_by_default(self):
        cfg = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
        enabled = cfg.get("plugins", {}).get("enabled", {})
        self.assertFalse(enabled.get("builtin.tracking.clipboard.windows", True))
        self.assertFalse(enabled.get("builtin.tracking.file_activity.windows", True))


if __name__ == "__main__":
    unittest.main()
