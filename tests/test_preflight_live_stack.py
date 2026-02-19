from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import preflight_live_stack


class PreflightLiveStackTests(unittest.TestCase):
    def test_preflight_success_with_required_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dataroot = root / "autocapture"
            media = dataroot / "media"
            media.mkdir(parents=True, exist_ok=True)
            (media / "frame1.png").write_bytes(b"png")
            (dataroot / "metadata.db").write_bytes(b"sqlite")
            out = root / "out.json"

            with (
                mock.patch.object(preflight_live_stack, "enforce_external_vllm_base_url", return_value="http://127.0.0.1:8000/v1"),
                mock.patch.object(preflight_live_stack, "check_external_vllm_ready", return_value={"ok": True, "selected_model": "internvl3_5_8b"}),
                mock.patch.object(
                    preflight_live_stack,
                    "_probe_service_contracts",
                    return_value={
                        "vllm_models": {"ok": True},
                        "embedder_models": {"ok": True},
                        "grounding_health": {"ok": True},
                        "hypervisor_statusz": {"ok": True},
                        "popup_health": {"ok": True},
                    },
                ),
            ):
                rc = preflight_live_stack.main(
                    [
                        "--dataroot",
                        str(dataroot),
                        "--output",
                        str(out),
                    ]
                )

            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(rc, 0)
            self.assertTrue(bool(payload.get("ready", False)))
            self.assertEqual(payload.get("failure_codes"), [])

    def test_preflight_emits_machine_readable_fail_codes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            missing_dataroot = root / "does_not_exist"
            out = root / "out.json"

            with (
                mock.patch.object(preflight_live_stack, "enforce_external_vllm_base_url", return_value="http://127.0.0.1:8000/v1"),
                mock.patch.object(preflight_live_stack, "check_external_vllm_ready", return_value={"ok": False, "error": "down"}),
                mock.patch.object(
                    preflight_live_stack,
                    "_probe_service_contracts",
                    return_value={
                        "vllm_models": {"ok": False},
                        "embedder_models": {"ok": False},
                        "grounding_health": {"ok": False},
                        "hypervisor_statusz": {"ok": False},
                        "popup_health": {"ok": False},
                    },
                ),
            ):
                rc = preflight_live_stack.main(
                    [
                        "--dataroot",
                        str(missing_dataroot),
                        "--output",
                        str(out),
                    ]
                )

            payload = json.loads(out.read_text(encoding="utf-8"))
            codes = set(str(x) for x in (payload.get("failure_codes") or []))
            self.assertEqual(rc, 1)
            self.assertIn("dataroot_missing", codes)
            self.assertIn("metadata_db_missing", codes)
            self.assertIn("media_dir_missing", codes)
            self.assertIn("media_empty", codes)
            self.assertIn("vllm_preflight_failed", codes)
            self.assertIn("svc_vllm_models_unreachable", codes)
            self.assertIn("svc_embedder_models_unreachable", codes)
            self.assertIn("svc_grounding_health_unreachable", codes)
            self.assertIn("svc_hypervisor_statusz_unreachable", codes)
            self.assertIn("svc_popup_health_unreachable", codes)

    def test_probe_service_contracts_uses_expected_paths(self) -> None:
        seen: list[str] = []

        def _fake_probe(url: str, timeout_s: float) -> dict[str, object]:
            seen.append(url)
            return {"ok": True, "url": url, "timeout_s": timeout_s}

        with mock.patch.object(preflight_live_stack, "_http_probe", side_effect=_fake_probe):
            out = preflight_live_stack._probe_service_contracts(2.0)

        self.assertTrue(bool(out["vllm_models"]["ok"]))
        self.assertIn("http://127.0.0.1:8000/v1/models", seen)
        self.assertIn("http://127.0.0.1:8001/v1/models", seen)
        self.assertIn("http://127.0.0.1:8011/health", seen)
        self.assertIn("http://127.0.0.1:34221/statusz", seen)
        self.assertIn("http://127.0.0.1:8787/health", seen)


if __name__ == "__main__":
    unittest.main()
