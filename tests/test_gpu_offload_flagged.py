import os
import tempfile
import unittest
from pathlib import Path

from autocapture.runtime.routing import route_gpu_heavy_job
from autocapture.runtime.wsl2_queue import Wsl2Queue


class GpuOffloadRoutingTests(unittest.TestCase):
    def test_gpu_offload_requires_flag(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            os.environ["AUTOCAPTURE_WSL2_QUEUE_FORCE"] = "1"
            q = Wsl2Queue(Path(td) / "queue", protocol_version=1, max_pending=1)

            local = route_gpu_heavy_job(
                config={},
                queue=q,
                job_name="ocr",
                payload={"frame_id": "x"},
                run_id="run_test",
            )
            self.assertEqual(local.target, "local")

            wsl2 = route_gpu_heavy_job(
                config={"gpu_heavy": {"target": "wsl2"}},
                queue=q,
                job_name="ocr",
                payload={"frame_id": "x"},
                run_id="run_test",
            )
            self.assertEqual(wsl2.target, "wsl2")
            self.assertTrue(wsl2.ok)
            self.assertTrue(wsl2.dispatch and wsl2.dispatch.ok)


if __name__ == "__main__":
    unittest.main()

