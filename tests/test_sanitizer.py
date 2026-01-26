import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths, load_config
from plugins.builtin.egress_sanitizer.plugin import EgressSanitizer
from autocapture_nx.plugin_system.api import PluginContext


class SanitizerTests(unittest.TestCase):
    def test_sanitizes_pii(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Load config and override data_dir
            paths = ConfigPaths(
                default_path=Path("config") / "default.json",
                user_path=Path(tmp) / "user.json",
                schema_path=Path("contracts") / "config_schema.json",
                backup_dir=Path(tmp) / "backup",
            )
            with open(paths.user_path, "w", encoding="utf-8") as handle:
                safe_tmp = tmp.replace("\\", "/")
                handle.write(
                    json.dumps(
                        {
                            "storage": {
                                "data_dir": safe_tmp,
                                "crypto": {
                                    "keyring_path": f"{safe_tmp}/keyring.json",
                                    "root_key_path": f"{safe_tmp}/root.key",
                                },
                            }
                        }
                    )
                )
            config = load_config(paths, safe_mode=False)
            context = PluginContext(config=config, get_capability=lambda _k: (_ for _ in ()).throw(Exception()), logger=lambda _m: None)
            sanitizer = EgressSanitizer("test", context)
            text = "Contact John Doe at john@example.com or 555-123-4567."
            result = sanitizer.sanitize_text(text)
            self.assertNotIn("john@example.com", result["text"])
            self.assertNotIn("555-123-4567", result["text"])
            self.assertRegex(result["text"], r"⟦ENT:EMAIL:")
            self.assertRegex(result["text"], r"⟦ENT:PHONE:")
            self.assertTrue(sanitizer.leak_check({"text": result["text"], "_tokens": result["tokens"]}))
            detok = sanitizer.detokenize_text(result["text"])
            self.assertIn("john@example.com", detok)


if __name__ == "__main__":
    unittest.main()
