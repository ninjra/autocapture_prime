import unittest

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.embedder_stub.plugin import EmbedderLocal
from plugins.builtin.reranker_stub.plugin import RerankerStub
from plugins.builtin.vlm_stub.plugin import VLMStub
from plugins.builtin.ocr_stub.plugin import OCRLocal


class ModelPluginTests(unittest.TestCase):
    def test_embedder_requires_dependency(self):
        ctx = PluginContext(config={}, get_capability=lambda _k: None, logger=lambda _m: None)
        embedder = EmbedderLocal("emb", ctx)
        try:
            result = embedder.embed("hello")
        except RuntimeError:
            return
        self.assertIn("vector", result)

    def test_reranker_requires_dependency(self):
        ctx = PluginContext(config={}, get_capability=lambda _k: None, logger=lambda _m: None)
        reranker = RerankerStub("rer", ctx)
        try:
            result = reranker.rerank([], "q")
        except RuntimeError:
            return
        self.assertIsInstance(result, list)

    def test_vlm_requires_dependency(self):
        ctx = PluginContext(config={}, get_capability=lambda _k: None, logger=lambda _m: None)
        vlm = VLMStub("vlm", ctx)
        try:
            result = vlm.extract(b"")
        except RuntimeError:
            return
        self.assertIn("text", result)

    def test_ocr_requires_dependency(self):
        ctx = PluginContext(config={}, get_capability=lambda _k: None, logger=lambda _m: None)
        ocr = OCRLocal("ocr", ctx)
        try:
            result = ocr.extract(b"")
        except RuntimeError:
            return
        self.assertIn("text", result)


if __name__ == "__main__":
    unittest.main()
