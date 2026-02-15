from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import unittest


def _load_module():
    path = pathlib.Path("tools/process_single_screenshot.py")
    spec = importlib.util.spec_from_file_location("process_single_screenshot_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProcessSingleScreenshotProfileGateTests(unittest.TestCase):
    def test_deep_merge_dict_overrides_recursively(self) -> None:
        mod = _load_module()
        base = {
            "runtime": {"golden_qh": {"enabled": False, "required_plugins": ["a"]}},
            "plugins": {"enabled": {"x": True}},
        }
        overlay = {
            "runtime": {"golden_qh": {"enabled": True, "required_plugins": ["a", "b"]}},
            "plugins": {"enabled": {"y": True}},
        }
        merged = mod._deep_merge_dict(base, overlay)
        self.assertTrue(merged["runtime"]["golden_qh"]["enabled"])
        self.assertEqual(merged["runtime"]["golden_qh"]["required_plugins"], ["a", "b"])
        self.assertTrue(merged["plugins"]["enabled"]["x"])
        self.assertTrue(merged["plugins"]["enabled"]["y"])

    def test_deep_merge_dict_unions_allowlists(self) -> None:
        mod = _load_module()
        base = {
            "plugins": {
                "allowlist": ["builtin.a"],
                "permissions": {"localhost_allowed_plugin_ids": ["builtin.a"]},
            }
        }
        overlay = {
            "plugins": {
                "allowlist": ["builtin.b", "builtin.a"],
                "permissions": {"localhost_allowed_plugin_ids": ["builtin.b"]},
            }
        }
        merged = mod._deep_merge_dict(base, overlay)
        self.assertEqual(merged["plugins"]["allowlist"], ["builtin.a", "builtin.b"])
        self.assertEqual(
            merged["plugins"]["permissions"]["localhost_allowed_plugin_ids"],
            ["builtin.a", "builtin.b"],
        )

    def test_plugin_gate_status_detects_missing_and_failed(self) -> None:
        mod = _load_module()
        load_report = {"loaded": ["builtin.a"], "failed": ["builtin.c"]}
        required = ["builtin.a", "builtin.b", "builtin.c"]
        status = mod._plugin_gate_status(load_report, required)
        self.assertFalse(status["ok"])
        self.assertEqual(status["missing_required"], ["builtin.b"])
        self.assertEqual(status["failed_required"], ["builtin.c"])

    def test_plugin_gate_status_passes_when_all_loaded(self) -> None:
        mod = _load_module()
        load_report = {"loaded": ["builtin.a", "builtin.b"], "failed": []}
        status = mod._plugin_gate_status(load_report, ["builtin.a", "builtin.b"])
        self.assertTrue(status["ok"])
        self.assertEqual(status["missing_required"], [])
        self.assertEqual(status["failed_required"], [])

    def test_should_stop_idle_loop_requires_state_when_not_done(self) -> None:
        mod = _load_module()
        self.assertFalse(mod._should_stop_idle_loop(done=False, stats={"sst_runs": 1, "state_runs": 0}))
        self.assertTrue(mod._should_stop_idle_loop(done=False, stats={"state_runs": 1}))
        self.assertTrue(mod._should_stop_idle_loop(done=True, stats={"state_runs": 0}))

    def test_should_require_vlm_from_required_plugins(self) -> None:
        mod = _load_module()
        self.assertTrue(mod._should_require_vlm(["builtin.vlm.vllm_localhost"]))
        self.assertFalse(mod._should_require_vlm(["builtin.ocr.basic"]))

    def test_truthy_env_helper(self) -> None:
        mod = _load_module()
        self.assertTrue(mod._is_truthy_env("1"))
        self.assertFalse(mod._is_truthy_env("0"))
        self.assertFalse(mod._is_truthy_env(""))

    def test_blocked_env_overrides_detects_truthy_only(self) -> None:
        mod = _load_module()
        old_a = os.environ.get("AUTOCAPTURE_VLM_TIMEOUT_S")
        old_b = os.environ.get("AUTOCAPTURE_VLM_MAX_TOKENS")
        try:
            os.environ["AUTOCAPTURE_VLM_TIMEOUT_S"] = "1"
            os.environ["AUTOCAPTURE_VLM_MAX_TOKENS"] = "0"
            blocked = mod._blocked_env_overrides(
                ["AUTOCAPTURE_VLM_TIMEOUT_S", "AUTOCAPTURE_VLM_MAX_TOKENS"]
            )
            self.assertEqual(blocked, ["AUTOCAPTURE_VLM_TIMEOUT_S"])
        finally:
            if old_a is None:
                os.environ.pop("AUTOCAPTURE_VLM_TIMEOUT_S", None)
            else:
                os.environ["AUTOCAPTURE_VLM_TIMEOUT_S"] = old_a
            if old_b is None:
                os.environ.pop("AUTOCAPTURE_VLM_MAX_TOKENS", None)
            else:
                os.environ["AUTOCAPTURE_VLM_MAX_TOKENS"] = old_b

    def test_resolve_strict_model_selection_auto_single(self) -> None:
        mod = _load_module()
        selected, source = mod._resolve_strict_model_selection(
            selected_model="",
            served_models=["internvl"],
            strict_golden=True,
        )
        self.assertEqual(selected, "internvl")
        self.assertEqual(source, "auto_single_served_model")

    def test_resolve_strict_model_selection_rejects_ambiguous(self) -> None:
        mod = _load_module()
        with self.assertRaises(RuntimeError):
            mod._resolve_strict_model_selection(
                selected_model="",
                served_models=["m1", "m2"],
                strict_golden=True,
            )


if __name__ == "__main__":
    unittest.main()
