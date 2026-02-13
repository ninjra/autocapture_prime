import unittest
from unittest.mock import patch

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.ocr_nemotron_torch.plugin import NemotronOCR


def _ctx(config=None):
    return PluginContext(
        config=config or {},
        get_capability=lambda _name: None,
        logger=lambda _msg: None,
    )


class NemotronOCRPluginTests(unittest.TestCase):
    def test_empty_frame_fails_closed(self) -> None:
        plugin = NemotronOCR("builtin.ocr.nemotron_torch", _ctx())
        out = plugin.extract(b"")
        self.assertEqual(out.get("text"), "")
        self.assertEqual(out.get("error"), "empty_frame")

    def test_prefers_local_when_available(self) -> None:
        plugin = NemotronOCR("builtin.ocr.nemotron_torch", _ctx())
        local = {
            "text": "hello world",
            "engine": "nemotron",
            "model_id": "local/model",
            "backend": "nemotron_torch_local",
        }
        with (
            patch.object(plugin, "_extract_local_torch", return_value=local),
            patch.object(plugin, "_extract_openai_compat", side_effect=AssertionError("fallback should not run")),
        ):
            out = plugin.extract(b"frame")
        self.assertEqual(out, local)

    def test_falls_back_to_openai_compat(self) -> None:
        plugin = NemotronOCR("builtin.ocr.nemotron_torch", _ctx())
        local = {
            "text": "",
            "engine": "nemotron",
            "model_id": "",
            "backend": "nemotron_torch_local",
            "error": "local_unavailable",
        }
        compat = {
            "text": "from vllm",
            "engine": "nemotron",
            "model_id": "model/v1",
            "backend": "openai_compat_ocr",
        }
        with (
            patch.object(plugin, "_extract_local_torch", return_value=local),
            patch.object(plugin, "_extract_openai_compat", return_value=compat),
        ):
            out = plugin.extract(b"frame")
        self.assertEqual(out, compat)

    def test_returns_compound_error_when_all_backends_fail(self) -> None:
        plugin = NemotronOCR("builtin.ocr.nemotron_torch", _ctx())
        local = {
            "text": "",
            "engine": "nemotron",
            "model_id": "",
            "backend": "nemotron_torch_local",
            "error": "local_failed",
        }
        compat = {
            "text": "",
            "engine": "nemotron",
            "model_id": "",
            "backend": "openai_compat_ocr",
            "error": "compat_failed",
        }
        with (
            patch.object(plugin, "_extract_local_torch", return_value=local),
            patch.object(plugin, "_extract_openai_compat", return_value=compat),
        ):
            out = plugin.extract(b"frame")
        self.assertEqual(out.get("text"), "")
        self.assertIn("local_failed", str(out.get("error") or ""))
        self.assertIn("compat_failed", str(out.get("error") or ""))


if __name__ == "__main__":
    unittest.main()
