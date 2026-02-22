from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest


def _load_module():
    path = pathlib.Path("tools/gate_plugin_enablement.py")
    spec = importlib.util.spec_from_file_location("gate_plugin_enablement_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GatePluginEnablementTests(unittest.TestCase):
    def test_evaluate_enablement_passes_when_required_plugins_are_healthy(self) -> None:
        mod = _load_module()
        required = ["p.alpha", "p.beta"]
        plugins_list = {
            "plugins": [
                {"plugin_id": "p.alpha", "allowlisted": True, "enabled": True, "hash_ok": True},
                {"plugin_id": "p.beta", "allowlisted": True, "enabled": True, "hash_ok": True},
            ]
        }
        load_report = {"report": {"loaded": ["p.alpha", "p.beta"], "failed": [], "errors": []}}
        out = mod.evaluate_enablement(plugins_list=plugins_list, load_report=load_report, required_ids=required)
        self.assertTrue(bool(out.get("ok", False)))
        self.assertEqual(int(out.get("failed_count", 0) or 0), 0)

    def test_evaluate_enablement_fails_with_explicit_reasons(self) -> None:
        mod = _load_module()
        required = ["p.alpha", "p.beta"]
        plugins_list = {
            "plugins": [
                {"plugin_id": "p.alpha", "allowlisted": False, "enabled": True, "hash_ok": False},
            ]
        }
        load_report = {"report": {"loaded": [], "failed": ["p.alpha"], "errors": []}}
        out = mod.evaluate_enablement(plugins_list=plugins_list, load_report=load_report, required_ids=required)
        self.assertFalse(bool(out.get("ok", True)))
        checks = out.get("checks", [])
        self.assertEqual(len(checks), 2)
        alpha = [row for row in checks if row.get("plugin_id") == "p.alpha"][0]
        beta = [row for row in checks if row.get("plugin_id") == "p.beta"][0]
        self.assertIn("allowlisted_false", alpha.get("reasons", []))
        self.assertIn("hash_not_ok", alpha.get("reasons", []))
        self.assertIn("in_failed_report", alpha.get("reasons", []))
        self.assertIn("missing_from_plugins_list", beta.get("reasons", []))
        self.assertIn("not_loaded", beta.get("reasons", []))


if __name__ == "__main__":
    unittest.main()
