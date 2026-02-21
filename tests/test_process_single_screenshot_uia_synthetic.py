from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


def _load_module():
    path = Path("tools/process_single_screenshot.py")
    spec = importlib.util.spec_from_file_location("process_single_screenshot_tool_uia", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Meta:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def put(self, record_id: str, payload: dict, **_kwargs) -> None:
        self.rows[str(record_id)] = dict(payload)

    def get(self, record_id: str, default=None):  # type: ignore[override]
        return self.rows.get(str(record_id), default)

    def keys(self):
        return list(self.rows.keys())


class ProcessSingleScreenshotUIASyntheticTests(unittest.TestCase):
    def test_build_frame_record_includes_uia_ref(self) -> None:
        mod = _load_module()
        frame = mod._build_frame_record(
            run_id="run_x",
            record_id="run_x/evidence.capture.frame/0",
            ts_utc="2026-02-19T00:00:00Z",
            image_bytes=b"\x89PNG\r\n\x1a\n",
            uia_ref={"record_id": "run_x/uia/0", "ts_utc": "2026-02-19T00:00:00Z", "content_hash": "a" * 64},
        )
        self.assertIn("uia_ref", frame)
        self.assertEqual(frame["uia_ref"]["record_id"], "run_x/uia/0")

    def test_inject_synthetic_uia_metadata_writes_metadata_record(self) -> None:
        mod = _load_module()
        meta = _Meta()
        with tempfile.TemporaryDirectory() as tmp:
            uia_ref, summary = mod._inject_synthetic_uia(
                metadata=meta,
                run_dir=Path(tmp),
                run_id="run_uia_meta",
                ts_utc="2026-02-19T00:00:00Z",
                mode="metadata",
                hash_mode="match",
                dataroot=str(Path(tmp) / "synthetic"),
                pack_json="",
            )
            self.assertTrue(summary["enabled"])
            self.assertEqual(summary["source"], "metadata")
            self.assertTrue(summary["metadata_record_written"])
            self.assertTrue(isinstance(uia_ref, dict))
            self.assertTrue(any(str(k).endswith("/uia/0") for k in meta.rows.keys()))

    def test_inject_synthetic_uia_fallback_does_not_write_metadata_record(self) -> None:
        mod = _load_module()
        meta = _Meta()
        with tempfile.TemporaryDirectory() as tmp:
            _uia_ref, summary = mod._inject_synthetic_uia(
                metadata=meta,
                run_dir=Path(tmp),
                run_id="run_uia_fallback",
                ts_utc="2026-02-19T00:00:00Z",
                mode="fallback",
                hash_mode="match",
                dataroot=str(Path(tmp) / "synthetic"),
                pack_json="",
            )
            self.assertTrue(summary["enabled"])
            self.assertEqual(summary["source"], "fallback")
            self.assertFalse(summary["metadata_record_written"])
            self.assertEqual(meta.rows, {})
            self.assertTrue(str(summary.get("fallback_latest_snap_json") or ""))

    def test_collect_uia_docs_counts_kinds(self) -> None:
        mod = _load_module()
        meta = _Meta()
        meta.put(
            "run_c/derived.sst.text/extra/a",
            {"doc_kind": "obs.uia.focus"},
        )
        meta.put(
            "run_c/derived.sst.text/extra/b",
            {"doc_kind": "obs.uia.context"},
        )
        meta.put(
            "run_c/derived.sst.text/extra/c",
            {"doc_kind": "obs.uia.operable"},
        )
        summary = mod._collect_uia_docs(meta, run_id="run_c")
        self.assertEqual(summary["count_by_kind"]["obs.uia.focus"], 1)
        self.assertEqual(summary["count_by_kind"]["obs.uia.context"], 1)
        self.assertEqual(summary["count_by_kind"]["obs.uia.operable"], 1)
        self.assertEqual(summary["total"], 3)

    def test_collect_uia_docs_falls_back_when_prefix_differs(self) -> None:
        mod = _load_module()
        meta = _Meta()
        meta.put(
            "run_other/derived.sst.text/extra/a",
            {"doc_kind": "obs.uia.focus"},
        )
        meta.put(
            "run_other/derived.sst.text/extra/b",
            {"doc_kind": "obs.uia.context"},
        )
        meta.put(
            "run_other/derived.sst.text/extra/c",
            {"doc_kind": "obs.uia.operable"},
        )
        summary = mod._collect_uia_docs(meta, run_id="run_c")
        self.assertEqual(summary["count_by_kind"]["obs.uia.focus"], 1)
        self.assertEqual(summary["count_by_kind"]["obs.uia.context"], 1)
        self.assertEqual(summary["count_by_kind"]["obs.uia.operable"], 1)
        self.assertEqual(summary["total"], 3)


if __name__ == "__main__":
    unittest.main()
