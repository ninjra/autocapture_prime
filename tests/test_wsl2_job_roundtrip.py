import json
import os
import tempfile
import unittest
from pathlib import Path

from autocapture.runtime.wsl2_queue import Wsl2Queue


class Wsl2QueueRoundTripTests(unittest.TestCase):
    def test_dispatch_and_ingest_response_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            os.environ["AUTOCAPTURE_WSL2_QUEUE_FORCE"] = "1"
            root = Path(td) / "queue"
            q = Wsl2Queue(root, protocol_version=1, max_pending=10)
            res = q.dispatch(job_name="gpu_heavy", payload={"x": 1}, run_id="run_test", allow_fallback=True)
            self.assertTrue(res.ok, msg=res)
            self.assertTrue(res.path and Path(res.path).exists())

            # Simulate worker writing a response.
            job_id = json.loads(Path(res.path).read_text(encoding="utf-8"))["job_id"]
            safe = str(job_id).replace("/", "_")
            q.responses_dir.mkdir(parents=True, exist_ok=True)
            (q.responses_dir / f"{safe}.json").write_text(json.dumps({"job_id": job_id, "ok": True, "result": 2}), encoding="utf-8")

            payload = q.await_response(job_id, timeout_s=2.0)
            self.assertIsNotNone(payload)
            self.assertEqual(payload.get("job_id"), job_id)
            self.assertTrue(payload.get("ok"))


if __name__ == "__main__":
    unittest.main()

