import unittest

from autocapture_nx.kernel.providers import capability_providers
from autocapture_nx.plugin_system.registry import CapabilityProxy, MultiCapabilityProxy


class _DummyOCR:
    def extract_tokens(self, _image_bytes):
        return []


class CapabilityProvidersTests(unittest.TestCase):
    def test_multi_capability_returns_providers(self) -> None:
        proxy_a = CapabilityProxy(_DummyOCR(), network_allowed=False, filesystem_policy=None, capability="ocr.engine")
        proxy_b = CapabilityProxy(_DummyOCR(), network_allowed=False, filesystem_policy=None, capability="ocr.engine")
        multi = MultiCapabilityProxy(
            "ocr.engine",
            [("builtin.ocr.a", proxy_a), ("builtin.ocr.b", proxy_b)],
            policy={"mode": "multi", "preferred": []},
        )
        providers = capability_providers(multi, "ocr.engine")
        self.assertEqual([pid for pid, _ in providers], ["builtin.ocr.a", "builtin.ocr.b"])


if __name__ == "__main__":
    unittest.main()
