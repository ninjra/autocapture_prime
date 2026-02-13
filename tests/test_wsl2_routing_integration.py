import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autocapture.runtime.governor import RuntimeGovernor
from autocapture.runtime.scheduler import Scheduler, Job
from autocapture.runtime.wsl2_queue import Wsl2Queue


class Wsl2RoutingTests(unittest.TestCase):
    def test_wsl2_dispatch_writes_queue_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = Wsl2Queue(tmp, protocol_version=1)
            governor = RuntimeGovernor(idle_window_s=5)
            scheduler = Scheduler(governor, wsl2_queue=queue)
            scheduler.update_config(
                {
                    "runtime": {
                        "routing": {
                            "gpu_heavy": {
                                "target": "wsl2",
                                "protocol_version": 1,
                                "shared_queue_dir": tmp,
                                "allow_fallback": False,
                                "distro": "",
                            }
                        }
                    }
                }
            )
            ran: list[str] = []
            scheduler.enqueue(
                Job(
                    name="gpu_task",
                    fn=lambda: ran.append("gpu"),
                    heavy=True,
                    gpu_heavy=True,
                    payload={"task": "gpu_task"},
                )
            )
            with patch.object(Wsl2Queue, "available", return_value=True):
                executed = scheduler.run_pending(
                    {"user_active": False, "idle_seconds": 100, "query_intent": False, "run_id": "run"}
                )
            self.assertEqual(executed, ["gpu_task"])
            files = list(queue.requests_dir.glob("*.json"))
            self.assertEqual(len(files), 1)
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload.get("job_name"), "gpu_task")

    def test_protocol_mismatch_defers_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "protocol.json").write_text(json.dumps({"protocol_version": 2}))
            queue = Wsl2Queue(tmp, protocol_version=1)
            governor = RuntimeGovernor(idle_window_s=5)
            scheduler = Scheduler(governor, wsl2_queue=queue)
            scheduler.update_config(
                {
                    "runtime": {
                        "routing": {
                            "gpu_heavy": {
                                "target": "wsl2",
                                "protocol_version": 1,
                                "shared_queue_dir": tmp,
                                "allow_fallback": False,
                                "distro": "",
                            }
                        }
                    }
                }
            )
            scheduler.enqueue(Job(name="gpu_task", fn=lambda: None, heavy=True, gpu_heavy=True))
            with patch.object(Wsl2Queue, "available", return_value=True):
                executed = scheduler.run_pending(
                    {"user_active": False, "idle_seconds": 100, "query_intent": False, "run_id": "run"}
                )
            self.assertEqual(executed, [])


if __name__ == "__main__":
    unittest.main()
