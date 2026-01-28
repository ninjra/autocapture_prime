import json
import unittest
from io import BytesIO

from PIL import Image, ImageDraw

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.embedder_stub.plugin import EmbedderLocal
from plugins.builtin.ocr_stub.plugin import OCRLocal
from plugins.builtin.reranker_stub.plugin import RerankerStub
from plugins.builtin.vlm_stub.plugin import VLMStub


class ModelPluginTests(unittest.TestCase):
    def _sample_image(self, text: str = "TEST") -> bytes:
        img = Image.new("RGB", (240, 80), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((10, 20), text, fill=(0, 0, 0))
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_embedder_returns_vector(self):
        ctx = PluginContext(config={}, get_capability=lambda _k: None, logger=lambda _m: None)
        embedder = EmbedderLocal("emb", ctx)
        result = embedder.embed("hello")
        self.assertIn("vector", result)
        self.assertGreater(len(result["vector"]), 0)

    def test_reranker_reranks(self):
        ctx = PluginContext(config={}, get_capability=lambda _k: None, logger=lambda _m: None)
        reranker = RerankerStub("rer", ctx)
        docs = [{"doc_id": "a", "text": "hello world"}, {"doc_id": "b", "text": "other"}]
        result = reranker.rerank(docs, "hello")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), len(docs))

    def test_vlm_extracts_layout(self):
        ctx = PluginContext(config={}, get_capability=lambda _k: None, logger=lambda _m: None)
        vlm = VLMStub("vlm", ctx)
        payload = vlm.extract(self._sample_image())
        self.assertIn("text", payload)
        parsed = json.loads(payload["text"])
        self.assertIn("elements", parsed)
        self.assertIn("edges", parsed)

    def test_ocr_extracts_tokens(self):
        ctx = PluginContext(config={}, get_capability=lambda _k: None, logger=lambda _m: None)
        ocr = OCRLocal("ocr", ctx)
        result = ocr.extract(self._sample_image("DATA"))
        self.assertIn("text", result)
        tokens = result.get("tokens", [])
        self.assertIsInstance(tokens, list)
        self.assertGreater(len(tokens), 0)


if __name__ == "__main__":
    unittest.main()
