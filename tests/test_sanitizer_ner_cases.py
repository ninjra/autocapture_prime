import os
import unittest

from plugins.builtin.egress_sanitizer.plugin import EgressSanitizer
from autocapture_nx.plugin_system.api import PluginContext


class _Context(PluginContext):
    def __init__(self, config: dict) -> None:
        super().__init__(config=config, get_capability=lambda _name: None, logger=lambda _msg: None)


class SanitizerNerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_bundle = os.environ.get("AUTOCAPTURE_BUNDLE_DIR")

    def tearDown(self) -> None:
        if self._orig_bundle is None:
            os.environ.pop("AUTOCAPTURE_BUNDLE_DIR", None)
        else:
            os.environ["AUTOCAPTURE_BUNDLE_DIR"] = self._orig_bundle

    def _config(self) -> dict:
        return {
            "privacy": {
                "egress": {
                    "recognizers": {
                        "ssn": False,
                        "credit_card": False,
                        "email": False,
                        "phone": False,
                        "ipv4": False,
                        "url": False,
                        "filepath": False,
                        "names": True,
                        "custom_regex": [],
                    }
                }
            }
        }

    def test_rule_based_name_detection(self) -> None:
        context = _Context(self._config())
        sanitizer = EgressSanitizer("test.egress", context)
        entities = sanitizer._find_entities("Alice Johnson met Bob Smith.")
        names = [ent.value for ent in entities if ent.kind == "NAME"]
        self.assertTrue(any("Alice Johnson" in name for name in names))

    def test_bundle_name_detection_union(self) -> None:
        os.environ["AUTOCAPTURE_BUNDLE_DIR"] = "tests/fixtures/bundles"
        context = _Context(self._config())
        sanitizer = EgressSanitizer("test.egress", context)
        entities = sanitizer._find_entities("We studied Ada Lovelace and Grace Hopper.")
        names = [ent.value for ent in entities if ent.kind == "NAME"]
        self.assertTrue(any("Ada" in name for name in names))
        self.assertTrue(any("Grace" in name for name in names))


if __name__ == "__main__":
    unittest.main()
