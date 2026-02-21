import json
import sys
import types
import unittest
from io import BytesIO

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency guard
    Image = None  # type: ignore[assignment]

from autocapture.indexing.vector import LocalEmbedder
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.reranker_stub.plugin import RerankerBasic
from plugins.builtin.vlm_stub.plugin import VLMStub


class EmbedderBackendTests(unittest.TestCase):
    def test_sentence_transformer_backend(self) -> None:
        module = types.ModuleType("sentence_transformers")

        class DummySentenceTransformer:
            def __init__(self, *args, **kwargs):
                _ = (args, kwargs)

            def eval(self):
                return None

            def get_sentence_embedding_dimension(self):
                return 3

            def encode(self, _texts, **_kwargs):
                return [[0.1, 0.2, 0.3]]

        module.SentenceTransformer = DummySentenceTransformer
        sys.modules["sentence_transformers"] = module
        try:
            embedder = LocalEmbedder("dummy-model")
            vec = embedder.embed("hello")
            self.assertEqual(vec, [0.1, 0.2, 0.3])
            identity = embedder.identity()
            self.assertEqual(identity.get("backend"), "sentence-transformers")
        finally:
            sys.modules.pop("sentence_transformers", None)


class RerankerBackendTests(unittest.TestCase):
    def test_cross_encoder_backend(self) -> None:
        module = types.ModuleType("sentence_transformers")

        class DummyCrossEncoder:
            def __init__(self, *args, **kwargs):
                _ = (args, kwargs)

            def predict(self, pairs):
                _ = pairs
                return [0.1, 0.9]

        module.CrossEncoder = DummyCrossEncoder
        sys.modules["sentence_transformers"] = module
        try:
            ctx = PluginContext(
                config={"models": {"reranker_path": "dummy-model"}},
                get_capability=lambda _k: None,
                logger=lambda _m: None,
            )
            reranker = RerankerBasic("reranker", ctx)
            docs = [{"doc_id": "a", "text": "foo"}, {"doc_id": "b", "text": "bar"}]
            result = reranker.rerank(docs, "query")
            self.assertEqual(result[0]["doc_id"], "b")
            self.assertEqual(result[0].get("rerank_backend"), "cross-encoder")
        finally:
            sys.modules.pop("sentence_transformers", None)


class VlmBackendTests(unittest.TestCase):
    def test_vlm_caption_pipeline(self) -> None:
        if Image is None:
            self.skipTest("Pillow not installed")

        module = types.ModuleType("transformers")

        class DummyPipeline:
            def __call__(self, _image, **_kwargs):
                return [{"generated_text": "Screen summary"}]

        def pipeline(_task, **_kwargs):
            return DummyPipeline()

        module.pipeline = pipeline
        sys.modules["transformers"] = module
        try:
            ctx = PluginContext(
                config={"models": {"vlm_path": "dummy-model"}},
                get_capability=lambda _k: None,
                logger=lambda _m: None,
            )
            vlm = VLMStub("vlm", ctx)
            img = Image.new("RGB", (40, 20), (255, 255, 255))
            buf = BytesIO()
            img.save(buf, format="PNG")
            payload = vlm.extract(buf.getvalue())
            self.assertEqual(payload.get("caption"), "Screen summary")
            parsed = json.loads(payload["text"])
            self.assertIn("elements", parsed)
        finally:
            sys.modules.pop("transformers", None)


if __name__ == "__main__":
    unittest.main()
