import io
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps as canonical_dumps
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.plugin_system.registry import CapabilityProxy, MultiCapabilityProxy
from autocapture_nx.processing.sst.pipeline import SSTPipeline
from plugins.builtin.processing_sst_uia_context.plugin import UIAContextStageHook

try:
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover - optional dependency guard
    Image = None
    ImageDraw = None


class _MetadataStore:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}

    def put_new(self, record_id: str, value: dict[str, Any]) -> None:
        if record_id in self.data:
            raise FileExistsError(record_id)
        self.data[record_id] = value

    def put(self, record_id: str, value: dict[str, Any]) -> None:
        self.data[record_id] = value

    def get(self, record_id: str, default: Any | None = None) -> Any:
        return self.data.get(record_id, default)

    def keys(self) -> list[str]:
        return list(self.data.keys())


class _EventBuilder:
    def journal_event(self, _event_type: str, payload: dict[str, Any], **_kwargs: Any) -> str:
        canonical_dumps(payload)
        return payload.get("artifact_id", "event")

    def ledger_entry(self, _stage: str, **kwargs: Any) -> str:
        payload = kwargs.get("payload", {})
        canonical_dumps(payload)
        return payload.get("artifact_id", "entry")


class _OCRProvider:
    def extract_tokens(self, _image_bytes: bytes) -> list[dict[str, Any]]:
        return [{"text": "uia plugin test", "bbox": (8, 8, 128, 32), "confidence": 0.96}]


class _System:
    def __init__(self, config: dict[str, Any], caps: dict[str, Any]) -> None:
        self.config = config
        self._caps = caps

    def has(self, name: str) -> bool:
        return name in self._caps

    def get(self, name: str) -> Any:
        return self._caps[name]


def _load_default_config() -> dict[str, Any]:
    return json.loads(Path("config/default.json").read_text(encoding="utf-8"))


def _make_image_bytes() -> bytes:
    if Image is None or ImageDraw is None:  # pragma: no cover - optional dependency guard
        raise RuntimeError("Pillow not installed")
    img = Image.new("RGB", (320, 180), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((12, 12), "UIA Hook", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _sample_snapshot(record_id: str, content_hash: str) -> dict[str, Any]:
    return {
        "record_type": "evidence.uia.snapshot",
        "record_id": record_id,
        "run_id": "run1",
        "ts_utc": "2024-01-01T00:00:00+00:00",
        "unix_ms_utc": 1704067200000,
        "hwnd": "0x000111",
        "window": {
            "title": "Outlook - Inbox",
            "process_path": "C:\\Program Files\\Microsoft Office\\outlook.exe",
            "pid": 4242,
        },
        "focus_path": [
            {
                "eid": "focus-1",
                "role": "Edit",
                "name": "Search",
                "aid": "SearchBox",
                "class": "Edit",
                "rect": [10, 10, 200, 42],
                "enabled": True,
                "offscreen": False,
            }
        ],
        "context_peers": [
            {
                "eid": "peer-1",
                "role": "ListItem",
                "name": "Message row",
                "aid": "MessageRow1",
                "class": "DataItem",
                "rect": [8, 56, 300, 96],
                "enabled": True,
                "offscreen": False,
            }
        ],
        "operables": [
            {
                "eid": "op-1",
                "role": "Button",
                "name": "Reply",
                "aid": "ReplyButton",
                "class": "Button",
                "rect": [12, 128, 100, 160],
                "enabled": True,
                "offscreen": False,
                "hot": True,
            },
            {
                "eid": "op-offscreen",
                "role": "Button",
                "name": "Hidden",
                "aid": "Hidden",
                "class": "Button",
                "rect": [0, 0, 10, 10],
                "enabled": True,
                "offscreen": True,
            },
        ],
        "stats": {"walk_ms": 12, "nodes_emitted": 14, "failures": 0},
        "content_hash": content_hash,
    }


class UIAContextPluginUnitTests(unittest.TestCase):
    def test_parses_snapshot_into_docs_with_bboxes_and_deterministic_ids(self) -> None:
        metadata = _MetadataStore()
        snapshot_id = "run1/uia/0"
        content_hash = "hash-abc"
        metadata.put(snapshot_id, _sample_snapshot(snapshot_id, content_hash))
        logs: list[str] = []

        ctx = PluginContext(
            config={
                "dataroot": "/mnt/d/autocapture",
                "allow_latest_snapshot_fallback": True,
                "require_hash_match": True,
                "max_focus_nodes": 64,
                "max_context_nodes": 64,
                "max_operable_nodes": 64,
                "drop_offscreen": True,
            },
            get_capability=lambda name: metadata if name == "storage.metadata" else None,
            logger=lambda msg: logs.append(str(msg)),
        )
        plugin = UIAContextStageHook("builtin.processing.sst.uia_context", ctx)
        payload = {
            "run_id": "run1",
            "record_id": "run1/segment/0",
            "frame_width": 320,
            "frame_height": 180,
            "record": {
                "uia_ref": {
                    "record_id": snapshot_id,
                    "ts_utc": "2024-01-01T00:00:00+00:00",
                    "content_hash": content_hash,
                }
            },
        }

        out_one = plugin.run_stage("index.text", payload)
        out_two = plugin.run_stage("index.text", payload)
        self.assertIsInstance(out_one, dict)
        self.assertIsInstance(out_two, dict)
        docs_one = out_one.get("extra_docs", []) if isinstance(out_one, dict) else []
        docs_two = out_two.get("extra_docs", []) if isinstance(out_two, dict) else []
        self.assertEqual(len(docs_one), 3)
        self.assertEqual(len(docs_two), 3)
        self.assertEqual(
            [str(doc.get("doc_id") or "") for doc in docs_one],
            [str(doc.get("doc_id") or "") for doc in docs_two],
        )
        expected_doc_ids = [
            f"run1/derived.sst.text/extra/{encode_record_id_component(f'uia-{snapshot_id}-focus-0')}",
            f"run1/derived.sst.text/extra/{encode_record_id_component(f'uia-{snapshot_id}-context-0')}",
            f"run1/derived.sst.text/extra/{encode_record_id_component(f'uia-{snapshot_id}-operable-0')}",
        ]
        self.assertEqual([str(doc.get("doc_id") or "") for doc in docs_one], expected_doc_ids)
        kinds = {str(doc.get("doc_kind") or "") for doc in docs_one if isinstance(doc, dict)}
        self.assertEqual(kinds, {"obs.uia.focus", "obs.uia.context", "obs.uia.operable"})

        for doc in docs_one:
            self.assertIsInstance(doc, dict)
            self.assertEqual(str(doc.get("record_type") or ""), str(doc.get("doc_kind") or ""))
            boxes = doc.get("bboxes", [])
            self.assertTrue(boxes)
            for box in boxes:
                self.assertEqual(len(box), 4)
                self.assertTrue(all(isinstance(v, int) for v in box))
                self.assertLessEqual(int(box[0]), int(box[2]))
                self.assertLessEqual(int(box[1]), int(box[3]))
            meta = doc.get("meta", {})
            self.assertEqual(str(meta.get("uia_record_id") or ""), snapshot_id)
            self.assertEqual(str(meta.get("uia_content_hash") or ""), content_hash)
            self.assertEqual(str(meta.get("hwnd") or ""), "0x000111")
            self.assertEqual(str(meta.get("window_title") or ""), "Outlook - Inbox")
            self.assertEqual(int(meta.get("window_pid") or 0), 4242)
            nodes = meta.get("uia_nodes", []) if isinstance(meta, dict) else []
            for node in nodes:
                norm = node.get("bbox_norm_bp", []) if isinstance(node, dict) else []
                self.assertEqual(len(norm), 4)
                self.assertTrue(all(isinstance(v, int) and 0 <= v <= 10000 for v in norm))
                self.assertFalse(bool(node.get("offscreen", False)))

    def test_missing_uia_ref_is_noop(self) -> None:
        metadata = _MetadataStore()
        ctx = PluginContext(
            config={},
            get_capability=lambda name: metadata if name == "storage.metadata" else None,
            logger=lambda _msg: None,
        )
        plugin = UIAContextStageHook("builtin.processing.sst.uia_context", ctx)
        out = plugin.run_stage("index.text", {"run_id": "run1", "record_id": "run1/segment/0", "record": {}})
        self.assertIsNone(out)

    def test_emits_all_obs_docs_when_some_sections_have_no_nodes(self) -> None:
        metadata = _MetadataStore()
        snapshot_id = "run1/uia/empty-sections"
        content_hash = "hash-empty-sections"
        snapshot = _sample_snapshot(snapshot_id, content_hash)
        snapshot["context_peers"] = []
        snapshot["operables"] = []
        metadata.put(snapshot_id, snapshot)
        ctx = PluginContext(
            config={
                "dataroot": "/mnt/d/autocapture",
                "allow_latest_snapshot_fallback": True,
                "require_hash_match": True,
                "max_focus_nodes": 8,
                "max_context_nodes": 8,
                "max_operable_nodes": 8,
                "drop_offscreen": True,
            },
            get_capability=lambda name: metadata if name == "storage.metadata" else None,
            logger=lambda _msg: None,
        )
        plugin = UIAContextStageHook("builtin.processing.sst.uia_context", ctx)
        payload = {
            "run_id": "run1",
            "record_id": "run1/segment/0",
            "frame_width": 320,
            "frame_height": 180,
            "record": {"uia_ref": {"record_id": snapshot_id, "content_hash": content_hash}},
        }
        out = plugin.run_stage("index.text", payload)
        self.assertIsInstance(out, dict)
        docs = out.get("extra_docs", []) if isinstance(out, dict) else []
        self.assertEqual(len(docs), 3)
        by_kind = {str(doc.get("doc_kind") or ""): doc for doc in docs if isinstance(doc, dict)}
        for kind in ("obs.uia.focus", "obs.uia.context", "obs.uia.operable"):
            self.assertIn(kind, by_kind)
            boxes = by_kind[kind].get("bboxes", [])
            self.assertTrue(boxes)

    def test_bad_hash_rejects_fallback_when_required(self) -> None:
        metadata = _MetadataStore()
        with tempfile.TemporaryDirectory() as tmpdir:
            uia_dir = Path(tmpdir) / "uia"
            uia_dir.mkdir(parents=True, exist_ok=True)
            snapshot_id = "run1/uia/fallback0"
            snapshot = _sample_snapshot(snapshot_id, "fallback-hash")
            raw = json.dumps(snapshot, sort_keys=True).encode("utf-8")
            (uia_dir / "latest.snap.json").write_bytes(raw)
            (uia_dir / "latest.snap.sha256").write_text("0" * 64, encoding="utf-8")

            ctx = PluginContext(
                config={
                    "dataroot": str(tmpdir),
                    "allow_latest_snapshot_fallback": True,
                    "require_hash_match": True,
                    "max_focus_nodes": 8,
                    "max_context_nodes": 8,
                    "max_operable_nodes": 8,
                    "drop_offscreen": True,
                },
                get_capability=lambda name: metadata if name == "storage.metadata" else None,
                logger=lambda _msg: None,
            )
            plugin = UIAContextStageHook("builtin.processing.sst.uia_context", ctx)
            payload = {
                "run_id": "run1",
                "record_id": "run1/segment/0",
                "frame_width": 320,
                "frame_height": 180,
                "record": {"uia_ref": {"record_id": snapshot_id}},
            }
            self.assertIsNone(plugin.run_stage("index.text", payload))

    def test_metadata_first_lookup_wins_over_latest_snapshot(self) -> None:
        metadata = _MetadataStore()
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_id = "run1/uia/metadata-priority"
            metadata_snapshot = _sample_snapshot(snapshot_id, "hash-meta")
            metadata_snapshot["window"] = {
                "title": "Metadata Window",
                "process_path": "C:\\Metadata\\app.exe",
                "pid": 7001,
            }
            metadata.put(snapshot_id, metadata_snapshot)

            uia_dir = Path(tmpdir) / "uia"
            uia_dir.mkdir(parents=True, exist_ok=True)
            fallback_snapshot = _sample_snapshot(snapshot_id, "hash-fallback")
            fallback_snapshot["window"] = {
                "title": "Fallback Window",
                "process_path": "C:\\Fallback\\app.exe",
                "pid": 7002,
            }
            raw = json.dumps(fallback_snapshot, sort_keys=True).encode("utf-8")
            (uia_dir / "latest.snap.json").write_bytes(raw)
            file_hash = hashlib.sha256(raw).hexdigest()
            (uia_dir / "latest.snap.sha256").write_text(f"{file_hash}  latest.snap.json\n", encoding="utf-8")

            ctx = PluginContext(
                config={
                    "dataroot": str(tmpdir),
                    "allow_latest_snapshot_fallback": True,
                    "require_hash_match": True,
                    "max_focus_nodes": 8,
                    "max_context_nodes": 8,
                    "max_operable_nodes": 8,
                    "drop_offscreen": True,
                },
                get_capability=lambda name: metadata if name == "storage.metadata" else None,
                logger=lambda _msg: None,
            )
            plugin = UIAContextStageHook("builtin.processing.sst.uia_context", ctx)
            payload = {
                "run_id": "run1",
                "record_id": "run1/segment/0",
                "frame_width": 320,
                "frame_height": 180,
                "record": {
                    "uia_ref": {
                        "record_id": snapshot_id,
                        "content_hash": "hash-meta",
                    }
                },
            }
            out = plugin.run_stage("index.text", payload)
            self.assertIsInstance(out, dict)
            docs = out.get("extra_docs", []) if isinstance(out, dict) else []
            self.assertEqual(len(docs), 3)
            for doc in docs:
                meta = doc.get("meta", {}) if isinstance(doc, dict) else {}
                self.assertEqual(meta.get("window_title"), "Metadata Window")
            diagnostics = out.get("diagnostics", []) if isinstance(out, dict) else []
            self.assertTrue(diagnostics)
            self.assertEqual(str(diagnostics[0].get("source") or ""), "metadata")

    def test_metadata_invalid_does_not_fallback(self) -> None:
        metadata = _MetadataStore()
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_id = "run1/uia/metadata-invalid"
            metadata.put(
                snapshot_id,
                {
                    "record_type": "invalid.record.type",
                    "record_id": snapshot_id,
                    "content_hash": "hash-meta",
                },
            )
            uia_dir = Path(tmpdir) / "uia"
            uia_dir.mkdir(parents=True, exist_ok=True)
            fallback_snapshot = _sample_snapshot(snapshot_id, "hash-meta")
            raw = json.dumps(fallback_snapshot, sort_keys=True).encode("utf-8")
            (uia_dir / "latest.snap.json").write_bytes(raw)
            file_hash = hashlib.sha256(raw).hexdigest()
            (uia_dir / "latest.snap.sha256").write_text(f"{file_hash}  latest.snap.json\n", encoding="utf-8")

            ctx = PluginContext(
                config={
                    "dataroot": str(tmpdir),
                    "allow_latest_snapshot_fallback": True,
                    "require_hash_match": True,
                    "max_focus_nodes": 8,
                    "max_context_nodes": 8,
                    "max_operable_nodes": 8,
                    "drop_offscreen": True,
                },
                get_capability=lambda name: metadata if name == "storage.metadata" else None,
                logger=lambda _msg: None,
            )
            plugin = UIAContextStageHook("builtin.processing.sst.uia_context", ctx)
            payload = {
                "run_id": "run1",
                "record_id": "run1/segment/0",
                "frame_width": 320,
                "frame_height": 180,
                "record": {
                    "uia_ref": {
                        "record_id": snapshot_id,
                        "content_hash": "hash-meta",
                    }
                },
            }
            self.assertIsNone(plugin.run_stage("index.text", payload))

    def test_doc_id_stability_uses_uia_record_id_not_frame_run_id(self) -> None:
        metadata = _MetadataStore()
        snapshot_id = "run_uia/uia/record-7"
        content_hash = "hash-uia-7"
        metadata.put(snapshot_id, _sample_snapshot(snapshot_id, content_hash))

        ctx = PluginContext(
            config={
                "dataroot": "/mnt/d/autocapture",
                "allow_latest_snapshot_fallback": True,
                "require_hash_match": True,
                "max_focus_nodes": 8,
                "max_context_nodes": 8,
                "max_operable_nodes": 8,
                "drop_offscreen": True,
            },
            get_capability=lambda name: metadata if name == "storage.metadata" else None,
            logger=lambda _msg: None,
        )
        plugin = UIAContextStageHook("builtin.processing.sst.uia_context", ctx)
        payload_a = {
            "run_id": "runA",
            "record_id": "runA/frame/1",
            "frame_width": 320,
            "frame_height": 180,
            "record": {"uia_ref": {"record_id": snapshot_id, "content_hash": content_hash}},
        }
        payload_b = {
            "run_id": "runB",
            "record_id": "runB/frame/1",
            "frame_width": 320,
            "frame_height": 180,
            "record": {"uia_ref": {"record_id": snapshot_id, "content_hash": content_hash}},
        }
        out_a = plugin.run_stage("index.text", payload_a)
        out_b = plugin.run_stage("index.text", payload_b)
        docs_a = out_a.get("extra_docs", []) if isinstance(out_a, dict) else []
        docs_b = out_b.get("extra_docs", []) if isinstance(out_b, dict) else []
        self.assertEqual(
            [str(doc.get("doc_id") or "") for doc in docs_a],
            [str(doc.get("doc_id") or "") for doc in docs_b],
        )

    def test_fallback_requires_sha_file_even_when_hash_match_disabled(self) -> None:
        metadata = _MetadataStore()
        with tempfile.TemporaryDirectory() as tmpdir:
            uia_dir = Path(tmpdir) / "uia"
            uia_dir.mkdir(parents=True, exist_ok=True)
            snapshot_id = "run1/uia/fallback-hash-file-required"
            snapshot = _sample_snapshot(snapshot_id, "fallback-hash")
            raw = json.dumps(snapshot, sort_keys=True).encode("utf-8")
            (uia_dir / "latest.snap.json").write_bytes(raw)
            # Intentionally omit latest.snap.sha256.

            ctx = PluginContext(
                config={
                    "dataroot": str(tmpdir),
                    "allow_latest_snapshot_fallback": True,
                    "require_hash_match": False,
                    "max_focus_nodes": 8,
                    "max_context_nodes": 8,
                    "max_operable_nodes": 8,
                    "drop_offscreen": True,
                },
                get_capability=lambda name: metadata if name == "storage.metadata" else None,
                logger=lambda _msg: None,
            )
            plugin = UIAContextStageHook("builtin.processing.sst.uia_context", ctx)
            payload = {
                "run_id": "run1",
                "record_id": "run1/segment/0",
                "frame_width": 320,
                "frame_height": 180,
                "record": {"uia_ref": {"record_id": snapshot_id}},
            }
            self.assertIsNone(plugin.run_stage("index.text", payload))


@unittest.skipIf(Image is None or ImageDraw is None, "Pillow is required for integration SST pipeline tests")
class UIAContextPluginIntegrationTests(unittest.TestCase):
    def test_pipeline_frame_with_uia_ref_emits_obs_uia_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _load_default_config()
            storage = config.setdefault("storage", {})
            storage["lexical_path"] = str(Path(tmpdir) / "lexical.db")
            storage["vector_path"] = str(Path(tmpdir) / "vector.db")
            storage["data_dir"] = str(tmpdir)
            storage["raw_first_local"] = True
            sst = config.setdefault("processing", {}).setdefault("sst", {})
            sst["heavy_always"] = True
            sst["redact_enabled"] = False

            metadata = _MetadataStore()
            snapshot_id = "run1/uia/2"
            content_hash = "hash-int-2"
            metadata.put(snapshot_id, _sample_snapshot(snapshot_id, content_hash))

            hook_ctx = PluginContext(
                config={
                    "dataroot": "/mnt/d/autocapture",
                    "allow_latest_snapshot_fallback": True,
                    "require_hash_match": True,
                    "max_focus_nodes": 64,
                    "max_context_nodes": 64,
                    "max_operable_nodes": 64,
                    "drop_offscreen": True,
                },
                get_capability=lambda name: metadata if name == "storage.metadata" else None,
                logger=lambda _msg: None,
            )
            hook = UIAContextStageHook("builtin.processing.sst.uia_context", hook_ctx)
            policy = {
                "mode": "multi",
                "preferred": [],
                "provider_ids": [],
                "fanout": True,
                "max_providers": 0,
            }
            proxies = [("builtin.processing.sst.uia_context", CapabilityProxy(hook, network_allowed=False))]
            stage_hooks = CapabilityProxy(
                MultiCapabilityProxy("processing.stage.hooks", proxies, policy),
                network_allowed=False,
            )

            system = _System(
                config,
                {
                    "storage.metadata": metadata,
                    "ocr.engine": _OCRProvider(),
                    "event.builder": _EventBuilder(),
                    "processing.stage.hooks": stage_hooks,
                },
            )

            pipeline = SSTPipeline(system, extractor_id="test.sst.uia", extractor_version="0.1.0")
            record = {
                "record_type": "evidence.capture.segment",
                "ts_utc": "2024-01-01T00:00:00+00:00",
                "container": {"type": "zip"},
                "uia_ref": {
                    "record_id": snapshot_id,
                    "ts_utc": "2024-01-01T00:00:00+00:00",
                    "content_hash": content_hash,
                },
            }
            result = pipeline.process_record(
                record_id="run1/segment/0",
                record=record,
                frame_bytes=_make_image_bytes(),
                allow_ocr=True,
                allow_vlm=False,
                should_abort=None,
                deadline_ts=time.time() + 30,
            )
            self.assertTrue(result.heavy_ran)

            docs: list[dict[str, Any]] = []
            for record_id, payload in metadata.data.items():
                if not record_id.startswith("run1/derived.sst.text/extra/"):
                    continue
                if not isinstance(payload, dict):
                    continue
                if not str(payload.get("doc_kind") or "").startswith("obs.uia."):
                    continue
                docs.append(payload)

            kinds = {str(doc.get("doc_kind") or "") for doc in docs}
            self.assertEqual(kinds, {"obs.uia.focus", "obs.uia.context", "obs.uia.operable"})
            for doc in docs:
                self.assertEqual(str(doc.get("record_type") or ""), str(doc.get("doc_kind") or ""))
                provenance = doc.get("provenance", {}) if isinstance(doc.get("provenance"), dict) else {}
                meta = doc.get("meta", {}) if isinstance(doc.get("meta"), dict) else {}
                if not meta and isinstance(provenance.get("meta"), dict):
                    meta = provenance.get("meta", {})
                self.assertEqual(str(meta.get("uia_record_id") or doc.get("uia_record_id") or ""), snapshot_id)
                self.assertEqual(str(meta.get("uia_content_hash") or doc.get("uia_content_hash") or ""), content_hash)
                self.assertEqual(str(meta.get("hwnd") or doc.get("hwnd") or ""), "0x000111")
                self.assertEqual(str(meta.get("window_title") or doc.get("window_title") or ""), "Outlook - Inbox")
                self.assertEqual(int(meta.get("window_pid") or doc.get("window_pid") or 0), 4242)
                raw_boxes = provenance.get("bboxes")
                if isinstance(raw_boxes, tuple):
                    boxes = list(raw_boxes)
                elif isinstance(raw_boxes, list):
                    boxes = raw_boxes
                else:
                    boxes = []
                self.assertTrue(boxes)
                for box in boxes:
                    self.assertEqual(len(box), 4)
                    self.assertTrue(all(isinstance(v, int) for v in box))
                    self.assertLessEqual(int(box[0]), int(box[2]))
                    self.assertLessEqual(int(box[1]), int(box[3]))


if __name__ == "__main__":
    unittest.main()
