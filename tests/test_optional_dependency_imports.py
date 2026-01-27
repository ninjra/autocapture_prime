import importlib
import sys
import unittest


HEAVY_MODULES = {
    "torch",
    "transformers",
    "sentence_transformers",
    "pytesseract",
}

MODULES_TO_CHECK = [
    "autocapture.indexing.vector",
    "autocapture.memory.answer_orchestrator",
    "autocapture.ingest.normalizer",
    "autocapture.ingest.table_extractor",
    "autocapture.ux.redaction",
    "plugins.builtin.embedder_stub.plugin",
    "plugins.builtin.ocr_stub.plugin",
    "plugins.builtin.reranker_stub.plugin",
    "plugins.builtin.vlm_stub.plugin",
]


class OptionalDependencyImportTests(unittest.TestCase):
    def test_no_heavy_imports_at_module_load(self) -> None:
        for module_name in MODULES_TO_CHECK:
            before = {name for name in HEAVY_MODULES if name in sys.modules}
            importlib.import_module(module_name)
            after = {name for name in HEAVY_MODULES if name in sys.modules}
            added = after - before
            self.assertFalse(
                added,
                f"{module_name} imported heavy optional modules at import time: {sorted(added)}",
            )


if __name__ == "__main__":
    unittest.main()
