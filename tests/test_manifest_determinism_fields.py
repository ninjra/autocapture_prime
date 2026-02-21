import unittest

from autocapture_nx.kernel.run_manifest import determinism_inputs
from autocapture_nx.kernel.schema_registry import SchemaRegistry


class ManifestDeterminismFieldsTests(unittest.TestCase):
    def test_run_manifest_has_determinism_inputs(self) -> None:
        cfg = {"runtime": {"run_id": "run_test", "timezone": "UTC"}, "kernel": {"rng": {"enabled": True, "strict": True}}}
        det = determinism_inputs(cfg)
        self.assertEqual(det.get("timezone"), "UTC")
        self.assertIn("locale", det)
        rng = det.get("rng", {})
        self.assertIsInstance(rng, dict)
        self.assertIn("enabled", rng)
        self.assertIn("strict", rng)
        self.assertIn("run_seed", rng)
        self.assertIn("run_seed_hex", rng)

        manifest = {
            "record_type": "system.run_manifest",
            "schema_version": 1,
            "run_id": "run_test",
            "ts_utc": "2026-02-07T00:00:00Z",
            "determinism": det,
        }
        registry = SchemaRegistry()
        schema = registry.load_schema_path("contracts/run_manifest.schema.json")
        issues = registry.validate(schema, manifest)
        self.assertEqual(issues, [], msg=registry.format_issues(issues))


if __name__ == "__main__":
    unittest.main()

