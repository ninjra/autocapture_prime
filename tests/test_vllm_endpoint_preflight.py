from __future__ import annotations

import os
import unittest
from unittest import mock

from autocapture_nx.inference import vllm_endpoint


class VllmEndpointPreflightTests(unittest.TestCase):
    def test_completion_timeout_scales_on_timeout_errors(self) -> None:
        calls: list[float] = []

        def _fake_preflight_once(**kwargs):
            calls.append(float(kwargs.get("timeout_completion_s") or 0.0))
            idx = len(calls)
            if idx == 1:
                return {"ok": False, "error": "completion_unreachable:TimeoutError"}
            if idx == 2:
                return {"ok": False, "error": "completion_unreachable:TimeoutError"}
            return {"ok": True, "models": ["internvl3_5_8b"], "selected_model": "internvl3_5_8b"}

        with (
            mock.patch.dict(
                os.environ,
                {
                    "AUTOCAPTURE_VLM_BASE_URL": "http://127.0.0.1:8000/v1",
                    "AUTOCAPTURE_VLM_MODEL": "internvl3_5_8b",
                    "AUTOCAPTURE_VLM_PREFLIGHT_RETRIES": "3",
                    "AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S": "12",
                    "AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_SCALE": "1.5",
                    "AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_MAX_S": "60",
                    "AUTOCAPTURE_VLM_ORCHESTRATOR_WARMUP_S": "0",
                    "AUTOCAPTURE_VLM_PREFLIGHT_RETRY_SLEEP_S": "0",
                    "AUTOCAPTURE_VLM_ORCHESTRATOR_POLL_S": "0",
                },
                clear=False,
            ),
            mock.patch.object(vllm_endpoint, "_preflight_once", side_effect=_fake_preflight_once),
            mock.patch.object(vllm_endpoint, "_invoke_orchestrator_once", return_value={"ok": True, "returncode": 0}),
            mock.patch.object(vllm_endpoint, "_read_watch_state", return_value=None),
        ):
            out = vllm_endpoint.check_external_vllm_ready(require_completion=True, auto_recover=True)

        self.assertTrue(bool(out.get("ok", False)))
        # Initial call uses configured timeout.
        self.assertAlmostEqual(calls[0], 12.0, places=3)
        # Recovery retries scale timeout after timeout failures.
        self.assertAlmostEqual(calls[1], 18.0, places=3)
        self.assertAlmostEqual(calls[2], 27.0, places=3)


if __name__ == "__main__":
    unittest.main()
