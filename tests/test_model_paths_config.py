import json
import unittest
from pathlib import Path


class ModelPathsConfigTests(unittest.TestCase):
    def test_default_model_paths_not_absolute(self) -> None:
        config = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
        models = config.get("models", {})
        for key in ("vlm_path", "reranker_path"):
            value = models.get(key)
            if value is None:
                continue
            self.assertFalse(Path(str(value)).is_absolute(), f"{key} should be relative or None")
        embedder = config.get("indexing", {}).get("embedder_model")
        if embedder is not None:
            self.assertFalse(Path(str(embedder)).is_absolute(), "embedder_model should be relative or None")


if __name__ == "__main__":
    unittest.main()
