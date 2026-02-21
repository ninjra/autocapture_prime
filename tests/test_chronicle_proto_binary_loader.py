from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from autocapture_prime.ingest.proto_decode import message_classes
from autocapture_prime.ingest.session_loader import SessionLoader


class ChronicleProtoBinaryLoaderTests(unittest.TestCase):
    def test_loader_decodes_raw_protobuf_batches(self) -> None:
        classes = message_classes()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "session_proto-0001"
            (root / "meta").mkdir(parents=True, exist_ok=True)
            (root / "frames").mkdir(parents=True, exist_ok=True)
            (root / "manifest.json").write_text(
                json.dumps({"session_id": "proto-0001", "qpc_frequency_hz": 10_000_000, "start_qpc_ticks": 1000}),
                encoding="utf-8",
            )
            (root / "COMPLETE.json").write_text("{}", encoding="utf-8")

            frame_batch = classes.FrameMetaBatch()
            f = frame_batch.items.add()
            f.session_id = "proto-0001"
            f.frame_index = 0
            f.qpc_ticks = 1000
            f.width = 640
            f.height = 360
            f.artifact_path = "frames/frame_000000.png"
            (root / "meta" / "frames.pb.zst").write_bytes(frame_batch.SerializeToString())

            input_batch = classes.InputEventBatch()
            e = input_batch.items.add()
            e.session_id = "proto-0001"
            e.event_index = 1
            e.qpc_ticks = 1200
            e.type = 1
            e.mouse.x = 100
            e.mouse.y = 120
            e.mouse.buttons = 1
            (root / "meta" / "input.pb.zst").write_bytes(input_batch.SerializeToString())

            det_batch = classes.DetectionBatch()
            d = det_batch.items.add()
            d.session_id = "proto-0001"
            d.frame_index = 0
            d.qpc_ticks = 1000
            u = d.elements.add()
            u.element_id = "elem1"
            u.type = 5
            u.text = "Inbox"
            u.confidence = 0.9
            u.bbox.x = 10
            u.bbox.y = 10
            u.bbox.w = 40
            u.bbox.h = 20
            (root / "meta" / "detections.pb.zst").write_bytes(det_batch.SerializeToString())

            (root / "frames" / "frame_000000.png").write_bytes(b"not_png_but_loader_only_tests_meta")

            loaded = SessionLoader(root).load()
            self.assertEqual(len(loaded.frames_meta), 1)
            self.assertEqual(loaded.frames_meta[0].get("artifact_path"), "frames/frame_000000.png")
            self.assertEqual(len(loaded.input_events), 1)
            self.assertEqual(loaded.input_events[0].get("mouse", {}).get("x"), 100)
            self.assertEqual(len(loaded.detections), 1)
            self.assertEqual(len(loaded.detections[0].get("elements", [])), 1)


if __name__ == "__main__":
    unittest.main()
