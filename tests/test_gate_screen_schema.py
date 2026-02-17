from __future__ import annotations

import unittest

from tools import gate_screen_schema as mod


class GateScreenSchemaTests(unittest.TestCase):
    def test_build_samples_have_expected_shape(self) -> None:
        ui_graph, provenance = mod._build_samples()
        self.assertEqual(ui_graph.get("schema_version"), 1)
        self.assertTrue(ui_graph.get("nodes"))
        self.assertEqual(provenance.get("schema_version"), 1)
        self.assertTrue(provenance.get("evidence"))

    def test_jsonschema_validate_detects_missing_required(self) -> None:
        schema = {
            "type": "object",
            "required": ["a"],
            "properties": {"a": {"type": "string"}},
        }
        ok, _detail = mod._jsonschema_validate(schema, {"a": "x"})
        self.assertTrue(ok)
        bad_ok, _detail_bad = mod._jsonschema_validate(schema, {})
        self.assertFalse(bad_ok)


if __name__ == "__main__":
    unittest.main()

