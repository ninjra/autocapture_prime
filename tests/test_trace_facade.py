import base64
import io
import tempfile
import unittest
import zipfile
from contextlib import contextmanager

from autocapture.core.hashing import hash_bytes
from autocapture_nx.kernel.derived_records import build_text_record
from autocapture_nx.kernel.event_builder import EventBuilder
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.ux.facade import UXFacade
from plugins.builtin.journal_basic.plugin import JournalWriter
from plugins.builtin.ledger_basic.plugin import LedgerWriter
from plugins.builtin.storage_memory.plugin import StorageMemoryPlugin


class FakeSystem:
    def __init__(self, config, caps):
        self.config = config
        self._caps = caps

    def get(self, name):
        return self._caps.get(name)

    def has(self, name):
        return name in self._caps


class DummyKernelMgr:
    def __init__(self, system):
        self._system = system

    @contextmanager
    def session(self):
        yield self._system

    def kernel(self):
        return None

    def last_error(self):
        return None


class StubTracker:
    def __init__(self, idle_seconds):
        self._idle_seconds = float(idle_seconds)

    def idle_seconds(self):
        return self._idle_seconds


class StubExtractor:
    def __init__(self, text):
        self._text = text

    def extract(self, _frame):
        return {"text": self._text}


def _zip_png() -> bytes:
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQImWNgYGD4DwABBAEAqD9G3QAAAABJRU5ErkJggg=="
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("frame.png", png_bytes)
    return buf.getvalue()


def _make_facade(tmp_dir, idle_seconds=999):
    config = {
        "runtime": {"run_id": "run1", "idle_window_s": 30, "activity": {"assume_idle_when_missing": False}},
        "storage": {
            "data_dir": tmp_dir,
            "lexical_path": f"{tmp_dir}/lexical.db",
            "vector_path": f"{tmp_dir}/vector.db",
        },
    }
    ctx = PluginContext(config=config, get_capability=lambda _n: None, logger=lambda _m: None)
    storage = StorageMemoryPlugin("storage.memory", ctx)
    caps = storage.capabilities()
    journal = JournalWriter("journal", ctx)
    ledger = LedgerWriter("ledger", ctx)
    builder = EventBuilder(config, journal, ledger, None)
    caps["event.builder"] = builder
    caps["tracking.input"] = StubTracker(idle_seconds)
    caps["ocr.engine"] = StubExtractor("hello trace")
    system = FakeSystem(config, caps)
    facade = UXFacade(persistent=False)
    facade._config = config
    facade._kernel_mgr = DummyKernelMgr(system)
    return facade, caps, config


def _segment_record(record_id, payload_bytes):
    return {
        "record_type": "evidence.capture.segment",
        "run_id": "run1",
        "segment_id": "seg0",
        "ts_start_utc": "2026-01-01T00:00:00+00:00",
        "ts_end_utc": "2026-01-01T00:00:10+00:00",
        "ts_utc": "2026-01-01T00:00:00+00:00",
        "width": 1,
        "height": 1,
        "container": {"type": "zip"},
        "content_type": "application/zip",
        "content_size": len(payload_bytes),
        "content_hash": hash_bytes(payload_bytes),
    }


class TraceFacadeTests(unittest.TestCase):
    def test_trace_latest_and_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            facade, caps, config = _make_facade(tmp)
            metadata = caps["storage.metadata"]
            media = caps["storage.media"]
            payload = _zip_png()
            record_id = "run1/segment/0"
            record = _segment_record(record_id, payload)
            metadata.put(record_id, record)
            media.put(record_id, payload)

            derived_id = (
                f"run1/derived.text.ocr/"
                f"{encode_record_id_component('stub')}/"
                f"{encode_record_id_component(record_id)}"
            )
            derived_payload = build_text_record(
                kind="ocr",
                text="hello trace",
                source_id=record_id,
                source_record=record,
                provider_id="stub",
                config=config,
                ts_utc=record["ts_utc"],
            )
            metadata.put_new(derived_id, derived_payload)

            latest = facade.trace_latest(record_type="evidence.capture.segment")
            self.assertEqual(latest.get("record_id"), record_id)

            detail = facade.trace_record(record_id)
            self.assertEqual(detail.get("record_id"), record_id)
            derived_ids = [item.get("record_id") for item in detail.get("derived", [])]
            self.assertIn(derived_id, derived_ids)

    def test_trace_preview_and_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            facade, caps, _config = _make_facade(tmp, idle_seconds=0)
            metadata = caps["storage.metadata"]
            media = caps["storage.media"]
            payload = _zip_png()
            record_id = "run1/segment/1"
            record = _segment_record(record_id, payload)
            metadata.put(record_id, record)
            media.put(record_id, payload)

            preview = facade.trace_preview(record_id)
            self.assertIn("data", preview)
            self.assertEqual(preview.get("content_type"), "image/png")

            blocked = facade.trace_process(record_id, allow_ocr=True, allow_vlm=False, force=False)
            self.assertFalse(blocked.get("ok"))
            self.assertEqual(blocked.get("error"), "user_active")

            result = facade.trace_process(record_id, allow_ocr=True, allow_vlm=False, force=True)
            self.assertTrue(result.get("ok"))
            derived_ids = result.get("derived_ids", [])
            self.assertTrue(derived_ids)
            derived_record = metadata.get(derived_ids[0])
            self.assertEqual(derived_record.get("record_type"), "derived.text.ocr")


if __name__ == "__main__":
    unittest.main()
