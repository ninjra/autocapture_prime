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

    def test_dispatch_is_idempotent_for_same_job_payload(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            os.environ["AUTOCAPTURE_WSL2_QUEUE_FORCE"] = "1"
            root = Path(td) / "queue"
            q = Wsl2Queue(root, protocol_version=1, max_pending=10, max_inflight=2)
            one = q.dispatch(job_name="gpu_heavy", payload={"x": 1}, run_id="run_test", allow_fallback=True)
            two = q.dispatch(job_name="gpu_heavy", payload={"x": 1}, run_id="run_test", allow_fallback=True)
            self.assertTrue(one.ok)
            self.assertTrue(two.ok)
            self.assertEqual(two.reason, "dedupe_pending")
            self.assertEqual(len(list(q.requests_dir.glob("*.json"))), 1)

    def test_token_backpressure_blocks_second_distinct_job_until_response(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            os.environ["AUTOCAPTURE_WSL2_QUEUE_FORCE"] = "1"
            root = Path(td) / "queue"
            q = Wsl2Queue(root, protocol_version=1, max_pending=10, max_inflight=1)
            first = q.dispatch(job_name="gpu_heavy", payload={"x": 1}, run_id="run_test", allow_fallback=True)
            second = q.dispatch(job_name="gpu_heavy", payload={"x": 2}, run_id="run_test", allow_fallback=True)
            self.assertTrue(first.ok)
            self.assertFalse(second.ok)
            self.assertEqual(second.reason, "token_backpressure")
            self.assertEqual(len(list(q.tokens_dir.glob("*.token"))), 1)

            job_id = json.loads(Path(first.path).read_text(encoding="utf-8"))["job_id"]
            safe = str(job_id).replace("/", "_")
            q.responses_dir.mkdir(parents=True, exist_ok=True)
            (q.responses_dir / f"{safe}.json").write_text(
                json.dumps({"job_id": job_id, "job_key": "", "ok": True}),
                encoding="utf-8",
            )
            _ = q.poll_responses(max_items=10)
            third = q.dispatch(job_name="gpu_heavy", payload={"x": 3}, run_id="run_test", allow_fallback=True)
            self.assertTrue(third.ok)


if __name__ == "__main__":
    unittest.main()
