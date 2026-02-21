import io
import tempfile
import unittest
import zipfile

from autocapture.core.hashing import hash_text, normalize_text
from autocapture_nx.kernel.derived_records import derived_text_record_id
from autocapture_nx.processing.idle import IdleProcessor
from autocapture.storage.retention import retention_eligibility_record_id
from autocapture.storage.stage1 import stage1_complete_record_id


class _MetadataStore:
    def __init__(self) -> None:
        self.data = {}
        self.get_calls = 0

    def put_new(self, record_id: str, value: dict) -> None:
        if record_id in self.data:
            raise FileExistsError(record_id)
        self.data[record_id] = value

    def put(self, record_id: str, value: dict) -> None:
        self.data[record_id] = value

    def get(self, record_id: str, default=None):
        self.get_calls += 1
        return self.data.get(record_id, default)

    def keys(self):
        return list(self.data.keys())


class _CheckpointFailMetadataStore(_MetadataStore):
    def put(self, record_id: str, value: dict) -> None:
        if record_id.endswith("/derived.idle.checkpoint"):
            raise ValueError("checkpoint_write_blocked")
        super().put(record_id, value)


class _MediaStore:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = blobs

    def get(self, record_id: str):
        return self._blobs.get(record_id)


class _Extractor:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    def extract(self, _frame: bytes):
        self.calls += 1
        return {"text": self._text}


class _EventBuilder:
    def __init__(self) -> None:
        self.journal = []
        self.ledger = []

    def journal_event(self, event_type, payload, **kwargs):
        self.journal.append((event_type, payload))
        return payload.get("derived_id") or "event"

    def ledger_entry(self, stage, inputs, outputs, **kwargs):
        self.ledger.append((stage, inputs, outputs))
        return "hash"


class _System:
    def __init__(self, config, metadata, media, ocr, vlm, events):
        self.config = config
        self._caps = {
            "storage.metadata": metadata,
            "storage.media": media,
            "ocr.engine": ocr,
            "vision.extractor": vlm,
            "event.builder": events,
        }

    def has(self, name: str) -> bool:
        return name in self._caps

    def get(self, name: str):
        return self._caps[name]


class IdleProcessorTests(unittest.TestCase):
    def test_checkpoint_id_is_stable_and_loads_legacy_record(self) -> None:
        config = {"runtime": {"run_id": "run1"}, "processing": {"idle": {"extractors": {"ocr": False, "vlm": False}}}}
        metadata = _MetadataStore()
        metadata.put(
            "run1/derived.idle.checkpoint",
            {
                "record_type": "derived.idle.checkpoint",
                "run_id": "run1",
                "ts_utc": "2024-01-01T00:00:00+00:00",
                "last_record_id": "run1/evidence.capture.frame/123",
                "processed_total": 77,
            },
        )
        system = _System(config, metadata, _MediaStore({}), None, None, _EventBuilder())
        processor = IdleProcessor(system)

        self.assertEqual(processor._checkpoint_id(), "system/derived.idle.checkpoint")
        checkpoint = processor._load_checkpoint()
        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint.last_record_id, "run1/evidence.capture.frame/123")
        self.assertEqual(checkpoint.processed_total, 77)

    def test_ordered_evidence_ids_prefers_canonical_ids_without_legacy_scan(self) -> None:
        config = {"runtime": {"run_id": "run1"}, "processing": {"idle": {"extractors": {"ocr": False, "vlm": False}}}}
        metadata = _MetadataStore()
        metadata.put("run1/evidence.capture.frame/2", {"record_type": "evidence.capture.frame", "ts_utc": "2024-01-01T00:00:02+00:00"})
        metadata.put("legacy_only_a", {"record_type": "derived.input.summary"})
        metadata.put("legacy_only_b", {"record_type": "evidence.capture.frame"})
        system = _System(config, metadata, _MediaStore({}), None, None, _EventBuilder())

        processor = IdleProcessor(system)
        evidence_ids = processor._ordered_evidence_ids("record_id")

        self.assertEqual(evidence_ids, ["run1/evidence.capture.frame/2"])
        self.assertEqual(metadata.get_calls, 0)

    def test_ordered_evidence_ids_legacy_fallback_when_no_canonical_ids(self) -> None:
        config = {"runtime": {"run_id": "run1"}, "processing": {"idle": {"extractors": {"ocr": False, "vlm": False}}}}
        metadata = _MetadataStore()
        metadata.put("legacy_record_1", {"record_type": "evidence.capture.frame", "ts_utc": "2024-01-01T00:00:01+00:00"})
        metadata.put("legacy_record_2", {"record_type": "evidence.capture.segment", "ts_utc": "2024-01-01T00:00:02+00:00"})
        metadata.put("other_record", {"record_type": "derived.input.summary", "ts_utc": "2024-01-01T00:00:03+00:00"})
        system = _System(config, metadata, _MediaStore({}), None, None, _EventBuilder())

        processor = IdleProcessor(system)
        evidence_ids = processor._ordered_evidence_ids("record_id")

        self.assertEqual(evidence_ids, ["legacy_record_1", "legacy_record_2"])
        self.assertGreaterEqual(metadata.get_calls, 1)

    def test_idle_processor_writes_derived_records(self) -> None:
        with tempfile.TemporaryDirectory():
            config = {
                "runtime": {"run_id": "run1"},
                "processing": {
                    "idle": {
                        "enabled": True,
                        "auto_start": False,
                        "max_items_per_run": 10,
                        "max_seconds_per_run": 5,
                        "sleep_ms": 1,
                        "max_concurrency_cpu": 1,
                        "max_concurrency_gpu": 1,
                        "extractors": {"ocr": True, "vlm": True},
                    }
                },
            }
            metadata = _MetadataStore()
            record_id = "run1/segment/0"
            metadata.put(
                record_id,
                {
                    "record_type": "evidence.capture.segment",
                    "ts_utc": "2024-01-01T00:00:00+00:00",
                    "container": {"type": "zip"},
                },
            )
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("frame_0.jpg", b"frame")
            media = _MediaStore({record_id: buf.getvalue()})
            events = _EventBuilder()
            system = _System(config, metadata, media, _Extractor("ocr text"), _Extractor("vlm text"), events)

            processor = IdleProcessor(system)
            stats = processor.process()
            self.assertEqual(stats.processed, 2)
            ocr_id = derived_text_record_id(
                kind="ocr",
                run_id="run1",
                provider_id="ocr.engine",
                source_id=record_id,
                config=config,
            )
            vlm_id = derived_text_record_id(
                kind="vlm",
                run_id="run1",
                provider_id="vision.extractor",
                source_id=record_id,
                config=config,
            )
            self.assertIn(ocr_id, metadata.data)
            self.assertIn(vlm_id, metadata.data)
            self.assertEqual(metadata.data[ocr_id]["content_hash"], hash_text(normalize_text("ocr text")))
            self.assertEqual(metadata.data[vlm_id]["content_hash"], hash_text(normalize_text("vlm text")))
            marker_id = retention_eligibility_record_id(record_id)
            self.assertIn(marker_id, metadata.data)
            self.assertEqual(metadata.data[marker_id].get("record_type"), "retention.eligible")

    def test_checkpoint_write_failure_is_fail_open(self) -> None:
        config = {
            "runtime": {"run_id": "run1"},
            "processing": {
                "idle": {
                    "enabled": True,
                    "auto_start": False,
                    "max_items_per_run": 1,
                    "max_seconds_per_run": 5,
                    "sleep_ms": 1,
                    "max_concurrency_cpu": 1,
                    "max_concurrency_gpu": 0,
                    "extractors": {"ocr": False, "vlm": False},
                },
                "sst": {"enabled": False},
            },
        }
        metadata = _CheckpointFailMetadataStore()
        record_id = "run1/evidence.capture.frame/0"
        metadata.put(
            record_id,
            {
                "record_type": "evidence.capture.frame",
                "ts_utc": "2024-01-01T00:00:00+00:00",
                "content_type": "image/png",
            },
        )
        media = _MediaStore({record_id: b"\x89PNG\r\n\x1a\nframe"})
        events = _EventBuilder()
        system = _System(config, metadata, media, None, None, events)

        processor = IdleProcessor(system)
        done, stats = processor.process_step()
        self.assertIsInstance(done, bool)
        self.assertIsNotNone(stats)
        self.assertNotIn("run1/derived.idle.checkpoint", metadata.data)

    def test_intelligent_batch_defers_repeat_hash_vlm_and_materializes_copy(self) -> None:
        with tempfile.TemporaryDirectory():
            config = {
                "runtime": {"run_id": "run1"},
                "processing": {
                    "idle": {
                        "enabled": True,
                        "auto_start": False,
                        "max_items_per_run": 10,
                        "max_seconds_per_run": 5,
                        "sleep_ms": 1,
                        "max_concurrency_cpu": 1,
                        "max_concurrency_gpu": 1,
                        "extractors": {"ocr": True, "vlm": True},
                        "intelligent_batch": {
                            "enabled": True,
                            "defer_vlm_on_hash_repeat": True,
                            "hash_repeat_window": 8,
                            "max_vlm_records_per_run": 0,
                            "max_pipeline_records_per_run": 0,
                        },
                    }
                },
            }
            metadata = _MetadataStore()
            record_a = "run1/evidence.capture.frame/0"
            record_b = "run1/evidence.capture.frame/1"
            payload = {
                "record_type": "evidence.capture.frame",
                "ts_utc": "2024-01-01T00:00:00+00:00",
                "content_hash": "same_hash",
                "content_type": "image/png",
            }
            metadata.put(record_a, dict(payload))
            metadata.put(record_b, dict(payload))
            frame = b"\x89PNG\r\n\x1a\nframe"
            media = _MediaStore({record_a: frame, record_b: frame})
            events = _EventBuilder()
            ocr = _Extractor("ocr text")
            vlm = _Extractor("vlm text")
            system = _System(config, metadata, media, ocr, vlm, events)

            processor = IdleProcessor(system)
            stats = processor.process()
            self.assertEqual(vlm.calls, 1)
            self.assertEqual(stats.vlm_deferred, 1)
            vlm_id_a = derived_text_record_id(
                kind="vlm",
                run_id="run1",
                provider_id="vision.extractor",
                source_id=record_a,
                config=config,
            )
            vlm_id_b = derived_text_record_id(
                kind="vlm",
                run_id="run1",
                provider_id="vision.extractor",
                source_id=record_b,
                config=config,
            )
            self.assertIn(vlm_id_a, metadata.data)
            self.assertIn(vlm_id_b, metadata.data)

    def test_intelligent_batch_caps_vlm_records_per_run(self) -> None:
        with tempfile.TemporaryDirectory():
            config = {
                "runtime": {"run_id": "run1"},
                "processing": {
                    "idle": {
                        "enabled": True,
                        "auto_start": False,
                        "max_items_per_run": 10,
                        "max_seconds_per_run": 5,
                        "sleep_ms": 1,
                        "max_concurrency_cpu": 1,
                        "max_concurrency_gpu": 1,
                        "extractors": {"ocr": False, "vlm": True},
                        "intelligent_batch": {
                            "enabled": True,
                            "defer_vlm_on_hash_repeat": True,
                            "hash_repeat_window": 8,
                            "max_vlm_records_per_run": 1,
                            "max_pipeline_records_per_run": 0,
                        },
                    }
                },
            }
            metadata = _MetadataStore()
            record_a = "run1/evidence.capture.frame/0"
            record_b = "run1/evidence.capture.frame/1"
            metadata.put(
                record_a,
                {
                    "record_type": "evidence.capture.frame",
                    "ts_utc": "2024-01-01T00:00:00+00:00",
                    "content_hash": "hash_a",
                    "content_type": "image/png",
                },
            )
            metadata.put(
                record_b,
                {
                    "record_type": "evidence.capture.frame",
                    "ts_utc": "2024-01-01T00:00:01+00:00",
                    "content_hash": "hash_b",
                    "content_type": "image/png",
                },
            )
            frame = b"\x89PNG\r\n\x1a\nframe"
            media = _MediaStore({record_a: frame, record_b: frame})
            events = _EventBuilder()
            vlm = _Extractor("vlm text")
            system = _System(config, metadata, media, None, vlm, events)

            processor = IdleProcessor(system)
            stats = processor.process()
            self.assertEqual(vlm.calls, 1)
            self.assertGreaterEqual(stats.vlm_throttled, 1)

    def test_stage1_backfill_marks_checkpointed_complete_frame_without_reextract(self) -> None:
        config = {
            "runtime": {"run_id": "run1"},
            "processing": {
                "idle": {
                    "enabled": True,
                    "auto_start": False,
                    "max_items_per_run": 10,
                    "max_seconds_per_run": 5,
                    "max_concurrency_cpu": 1,
                    "max_concurrency_gpu": 0,
                    "extractors": {"ocr": True, "vlm": False},
                    "stage1_marker_backfill": {"enabled": True, "max_records_per_run": 10},
                },
                "sst": {"enabled": False},
            },
        }
        metadata = _MetadataStore()
        frame_id = "run1/evidence.capture.frame/0"
        uia_id = "run1/evidence.uia.snapshot/0"
        metadata.put(
            frame_id,
            {
                "record_type": "evidence.capture.frame",
                "run_id": "run1",
                "ts_utc": "2024-01-01T00:00:00+00:00",
                "blob_path": "media/frame0.png",
                "content_hash": "hash_frame_0",
                "uia_ref": {"record_id": uia_id, "content_hash": "uia_hash_0"},
                "input_ref": {"record_id": "run1/evidence.input.batch/0"},
                "content_type": "image/png",
                "desktop_rect": [0, 0, 1920, 1080],
            },
        )
        metadata.put(
            uia_id,
            {
                "record_type": "evidence.uia.snapshot",
                "record_id": uia_id,
                "run_id": "run1",
                "ts_utc": "2024-01-01T00:00:00+00:00",
                "unix_ms_utc": 1704067200000,
                "hwnd": "101",
                "window": {"title": "Outlook", "process_path": "outlook.exe", "pid": 1234},
                "focus_path": [{"eid": "n1", "role": "button", "name": "Complete", "rect": [10, 10, 80, 30], "enabled": True, "offscreen": False}],
                "context_peers": [],
                "operables": [{"eid": "n2", "role": "button", "name": "View", "rect": [90, 10, 150, 30], "enabled": True, "offscreen": False}],
                "stats": {"walk_ms": 2, "nodes_emitted": 2, "failures": 0},
                "content_hash": "uia_hash_0",
            },
        )
        checkpoint_id = "system/derived.idle.checkpoint"
        metadata.put(
            checkpoint_id,
            {
                "record_type": "derived.idle.checkpoint",
                "run_id": "run1",
                "ts_utc": "2024-01-01T00:00:01+00:00",
                "last_record_id": frame_id,
                "processed_total": 1,
            },
        )
        ocr_id = derived_text_record_id(
            kind="ocr",
            run_id="run1",
            provider_id="ocr.engine",
            source_id=frame_id,
            config=config,
        )
        metadata.put(
            ocr_id,
            {
                "record_type": "derived.text.ocr",
                "run_id": "run1",
                "source_record_id": frame_id,
                "text": "already complete",
            },
        )
        media = _MediaStore({frame_id: b"\x89PNG\r\n\x1a\nframe"})
        ocr = _Extractor("should not run")
        events = _EventBuilder()
        system = _System(config, metadata, media, ocr, None, events)

        processor = IdleProcessor(system)
        done, stats = processor.process_step(budget_ms=0)

        self.assertTrue(done)
        self.assertEqual(ocr.calls, 0)
        self.assertGreaterEqual(stats.stage1_backfill_marked_records, 1)
        self.assertIn(stage1_complete_record_id(frame_id), metadata.data)
        self.assertIn(retention_eligibility_record_id(frame_id), metadata.data)

    def test_stage1_backfill_upgrades_legacy_retention_marker_for_frame(self) -> None:
        config = {
            "runtime": {"run_id": "run1"},
            "processing": {
                "idle": {
                    "enabled": True,
                    "auto_start": False,
                    "max_items_per_run": 10,
                    "max_seconds_per_run": 5,
                    "max_concurrency_cpu": 1,
                    "max_concurrency_gpu": 0,
                    "extractors": {"ocr": True, "vlm": False},
                    "stage1_marker_backfill": {"enabled": True, "max_records_per_run": 10},
                },
                "sst": {"enabled": False},
            },
        }
        metadata = _MetadataStore()
        frame_id = "run1/evidence.capture.frame/0"
        uia_id = "run1/evidence.uia.snapshot/0"
        metadata.put(
            frame_id,
            {
                "record_type": "evidence.capture.frame",
                "run_id": "run1",
                "ts_utc": "2024-01-01T00:00:00+00:00",
                "blob_path": "media/frame0.png",
                "content_hash": "hash_frame_0",
                "uia_ref": {"record_id": uia_id, "content_hash": "uia_hash_0"},
                "input_ref": {"record_id": "run1/evidence.input.batch/0"},
                "content_type": "image/png",
                "desktop_rect": [0, 0, 1920, 1080],
            },
        )
        metadata.put(
            uia_id,
            {
                "record_type": "evidence.uia.snapshot",
                "record_id": uia_id,
                "run_id": "run1",
                "ts_utc": "2024-01-01T00:00:00+00:00",
                "unix_ms_utc": 1704067200000,
                "hwnd": "101",
                "window": {"title": "Outlook", "process_path": "outlook.exe", "pid": 1234},
                "focus_path": [{"eid": "n1", "role": "button", "name": "Complete", "rect": [10, 10, 80, 30], "enabled": True, "offscreen": False}],
                "context_peers": [],
                "operables": [{"eid": "n2", "role": "button", "name": "View", "rect": [90, 10, 150, 30], "enabled": True, "offscreen": False}],
                "stats": {"walk_ms": 2, "nodes_emitted": 2, "failures": 0},
                "content_hash": "uia_hash_0",
            },
        )
        checkpoint_id = "system/derived.idle.checkpoint"
        metadata.put(
            checkpoint_id,
            {
                "record_type": "derived.idle.checkpoint",
                "run_id": "run1",
                "ts_utc": "2024-01-01T00:00:01+00:00",
                "last_record_id": frame_id,
                "processed_total": 1,
            },
        )
        metadata.put(
            stage1_complete_record_id(frame_id),
            {
                "record_type": "derived.ingest.stage1.complete",
                "run_id": "run1",
                "source_record_id": frame_id,
                "complete": True,
            },
        )
        metadata.put(
            retention_eligibility_record_id(frame_id),
            {
                "record_type": "retention.eligible",
                "run_id": "run1",
                "source_record_id": frame_id,
                "source_record_type": "evidence.capture.frame",
                "eligible": True,
                # Legacy marker intentionally missing stage1_contract_validated.
            },
        )
        ocr_id = derived_text_record_id(
            kind="ocr",
            run_id="run1",
            provider_id="ocr.engine",
            source_id=frame_id,
            config=config,
        )
        metadata.put(
            ocr_id,
            {
                "record_type": "derived.text.ocr",
                "run_id": "run1",
                "source_record_id": frame_id,
                "text": "already complete",
            },
        )
        media = _MediaStore({frame_id: b"\x89PNG\r\n\x1a\nframe"})
        ocr = _Extractor("should not run")
        events = _EventBuilder()
        system = _System(config, metadata, media, ocr, None, events)

        processor = IdleProcessor(system)
        done, stats = processor.process_step(budget_ms=0)

        self.assertTrue(done)
        self.assertEqual(ocr.calls, 0)
        self.assertGreaterEqual(stats.stage1_backfill_marked_records, 1)
        marker = metadata.data[retention_eligibility_record_id(frame_id)]
        self.assertTrue(bool(marker.get("stage1_contract_validated", False)))
        self.assertFalse(bool(marker.get("quarantine_pending", False)))

    def test_stage1_backfill_inserts_uia_obs_docs_when_snapshot_present(self) -> None:
        config = {
            "runtime": {"run_id": "run1"},
            "storage": {"data_dir": "/tmp/autocapture"},
            "processing": {
                "idle": {
                    "enabled": True,
                    "auto_start": False,
                    "max_items_per_run": 10,
                    "max_seconds_per_run": 5,
                    "max_concurrency_cpu": 1,
                    "max_concurrency_gpu": 0,
                    "extractors": {"ocr": True, "vlm": False},
                    "stage1_marker_backfill": {"enabled": True, "max_records_per_run": 10},
                },
                "sst": {"enabled": False},
            },
        }
        metadata = _MetadataStore()
        frame_id = "run1/evidence.capture.frame/0"
        uia_id = "run1/evidence.uia.snapshot/0"
        metadata.put(
            frame_id,
            {
                "record_type": "evidence.capture.frame",
                "run_id": "run1",
                "ts_utc": "2024-01-01T00:00:00+00:00",
                "blob_path": "media/frame0.png",
                "content_hash": "hash_frame_0",
                "uia_ref": {"record_id": uia_id, "content_hash": "uia_hash_0"},
                "input_ref": {"record_id": "run1/evidence.input.batch/0"},
                "content_type": "image/png",
                "desktop_rect": [0, 0, 1920, 1080],
            },
        )
        metadata.put(
            uia_id,
            {
                "record_type": "evidence.uia.snapshot",
                "record_id": uia_id,
                "run_id": "run1",
                "ts_utc": "2024-01-01T00:00:00+00:00",
                "unix_ms_utc": 1704067200000,
                "hwnd": "101",
                "window": {"title": "Outlook", "process_path": "outlook.exe", "pid": 1234},
                "focus_path": [{"eid": "n1", "role": "button", "name": "Complete", "rect": [10, 10, 80, 30], "enabled": True, "offscreen": False}],
                "context_peers": [],
                "operables": [{"eid": "n2", "role": "button", "name": "View", "rect": [90, 10, 150, 30], "enabled": True, "offscreen": False}],
                "stats": {"walk_ms": 2, "nodes_emitted": 2, "failures": 0},
                "content_hash": "uia_hash_0",
            },
        )
        metadata.put(
            stage1_complete_record_id(frame_id),
            {
                "record_type": "derived.ingest.stage1.complete",
                "run_id": "run1",
                "source_record_id": frame_id,
                "complete": True,
            },
        )
        metadata.put(
            retention_eligibility_record_id(frame_id),
            {
                "record_type": "retention.eligible",
                "run_id": "run1",
                "source_record_id": frame_id,
                "source_record_type": "evidence.capture.frame",
                "eligible": True,
                "stage1_contract_validated": True,
                "quarantine_pending": False,
            },
        )
        checkpoint_id = "system/derived.idle.checkpoint"
        metadata.put(
            checkpoint_id,
            {
                "record_type": "derived.idle.checkpoint",
                "run_id": "run1",
                "ts_utc": "2024-01-01T00:00:01+00:00",
                "last_record_id": frame_id,
                "processed_total": 1,
            },
        )
        ocr_id = derived_text_record_id(
            kind="ocr",
            run_id="run1",
            provider_id="ocr.engine",
            source_id=frame_id,
            config=config,
        )
        metadata.put(
            ocr_id,
            {
                "record_type": "derived.text.ocr",
                "run_id": "run1",
                "source_record_id": frame_id,
                "text": "already complete",
            },
        )
        media = _MediaStore({frame_id: b"\x89PNG\r\n\x1a\nframe"})
        ocr = _Extractor("should not run")
        events = _EventBuilder()
        system = _System(config, metadata, media, ocr, None, events)

        processor = IdleProcessor(system)
        done, stats = processor.process_step(budget_ms=0)

        self.assertTrue(done)
        self.assertEqual(ocr.calls, 0)
        obs_rows = [
            row
            for row in metadata.data.values()
            if isinstance(row, dict) and str(row.get("record_type") or "").startswith("obs.uia.")
        ]
        self.assertGreaterEqual(len(obs_rows), 3)
        self.assertGreaterEqual(int(stats.stage1_uia_docs_inserted), 3)


if __name__ == "__main__":
    unittest.main()
