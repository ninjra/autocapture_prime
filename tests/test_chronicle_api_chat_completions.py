from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from autocapture_prime.config import load_prime_config
from autocapture_prime.ingest.pipeline import ingest_one_session
from autocapture_prime.ingest.session_scanner import SessionCandidate
from services.chronicle_api.app import create_app


class ChronicleApiChatTests(unittest.TestCase):
    def test_chat_completion_forwards_with_retrieval_metadata(self) -> None:
        fixture_root = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "chronicle_spool"
        session_dir = fixture_root / "session_test-0001"
        candidate = SessionCandidate(
            session_id="test-0001",
            session_dir=session_dir,
            manifest_path=session_dir / "manifest.json",
        )
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "cfg.yaml"
            cfg_path.write_text(
                "\n".join(
                    [
                        "spool:",
                        f"  root_dir_linux: {fixture_root}",
                        "storage:",
                        f"  root_dir: {Path(td) / 'out'}",
                        "ocr:",
                        "  engine: tesseract",
                        "layout:",
                        "  engine: uied",
                        "vllm:",
                        "  base_url: http://127.0.0.1:8000",
                        "  model: OpenGVLab/InternVL3_5-8B",
                    ]
                ),
                encoding="utf-8",
            )
            cfg = load_prime_config(cfg_path)
            ingest_one_session(candidate, cfg)
            app = create_app(cfg_path)
            client = TestClient(app)
            with patch(
                "services.chronicle_api.app._call_vllm",
                return_value={
                    "id": "cmpl-test",
                    "object": "chat.completion",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
                },
            ):
                resp = client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "OpenGVLab/InternVL3_5-8B",
                        "messages": [{"role": "user", "content": "who is in the task"}],
                    },
                )
            self.assertEqual(resp.status_code, 200)
            payload = resp.json()
            self.assertIn("usage", payload)
            self.assertIn("chronicle_retrieval_hits", payload["usage"])
            self.assertIn("chronicle_retrieval", payload["usage"])
            self.assertIsInstance(payload["usage"]["chronicle_retrieval"], list)
            qa_metrics = Path(td) / "out" / "metrics" / "qa_metrics.ndjson"
            self.assertTrue(qa_metrics.exists())
            line = qa_metrics.read_text(encoding="utf-8").strip().splitlines()[-1]
            row = json.loads(line)
            self.assertIn("query_sha256", row)
            self.assertIn("plugin_path", row)
            self.assertIn("evidence_order_hash", row)


if __name__ == "__main__":
    unittest.main()
