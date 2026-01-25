import unittest

from autocapture.plugins.kinds import REQUIRED_KINDS


class PluginKindsRegistryTests(unittest.TestCase):
    def test_required_kinds_present(self) -> None:
        required = {
            "capture.source",
            "capture.encoder",
            "activity.signal",
            "storage.blob_backend",
            "storage.media_backend",
            "spans_v2.backend",
            "ocr.engine",
            "llm.provider",
            "decode.backend",
            "embedder.text",
            "vector.backend",
            "retrieval.strategy",
            "reranker.provider",
            "compressor",
            "verifier",
            "egress.sanitizer",
            "export.bundle",
            "import.bundle",
            "ui.panel",
            "ui.overlay",
            "prompt.bundle",
            "training.pipeline",
            "research.source",
            "research.watchlist",
        }
        self.assertTrue(required.issubset(set(REQUIRED_KINDS)))
        self.assertEqual(len(REQUIRED_KINDS), len(set(REQUIRED_KINDS)))


if __name__ == "__main__":
    unittest.main()
