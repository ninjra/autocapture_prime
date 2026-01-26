import unittest

from autocapture.core.hashing import hash_canonical
from autocapture.training.datasets import dataset_from_items
from autocapture.training.pipelines import TrainingPipeline


class TrainingManifestSchemaTests(unittest.TestCase):
    def test_manifest_hash(self) -> None:
        dataset = dataset_from_items([{"text": "alpha"}], name="demo")
        pipeline = TrainingPipeline(method="lora")
        manifest = pipeline.run(
            dataset=dataset,
            params={"lr": 0.01},
            run_id="run1",
            created_at="2026-01-01T00:00:00Z",
            dry_run=True,
        )
        stripped = dict(manifest)
        manifest_hash = stripped.pop("manifest_hash")
        self.assertEqual(manifest_hash, hash_canonical(stripped))
        self.assertEqual(manifest["method"], "lora")


if __name__ == "__main__":
    unittest.main()
