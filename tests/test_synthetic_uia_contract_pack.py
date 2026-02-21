from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load_module():
    path = Path("tools/synthetic_uia_contract_pack.py")
    spec = importlib.util.spec_from_file_location("synthetic_uia_contract_pack_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SyntheticUIAContractPackTests(unittest.TestCase):
    def test_build_contract_pack_has_required_contract_fields(self) -> None:
        mod = _load_module()
        pack = mod.build_contract_pack(
            run_id="run_a",
            uia_record_id="run_a/uia/0",
            ts_utc="2026-02-19T00:00:00Z",
            hash_mode="match",
            focus_nodes=2,
            context_nodes=3,
            operable_nodes=4,
        )
        self.assertIn("uia_ref", pack)
        self.assertIn("snapshot", pack)
        self.assertIn("metadata_record", pack)
        snapshot = pack["snapshot"]
        self.assertEqual(snapshot["record_type"], "evidence.uia.snapshot")
        self.assertEqual(len(snapshot["focus_path"]), 2)
        self.assertEqual(len(snapshot["context_peers"]), 3)
        self.assertEqual(len(snapshot["operables"]), 4)
        self.assertTrue(str(snapshot["content_hash"]))

    def test_write_contract_pack_emits_files_and_hashes(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            out = mod.write_contract_pack(
                out_dir=Path(tmp),
                run_id="run_b",
                uia_record_id="run_b/uia/0",
                ts_utc="2026-02-19T00:00:00Z",
                hash_mode="match",
                focus_nodes=1,
                context_nodes=1,
                operable_nodes=1,
                write_hash_file=True,
            )
            self.assertTrue(out["ok"])
            pack_path = Path(out["pack_path"])
            self.assertTrue(pack_path.exists())
            pack = json.loads(pack_path.read_text(encoding="utf-8"))
            snap_path = Path(pack["fallback"]["latest_snap_json"])
            sha_path = Path(pack["fallback"]["latest_snap_sha256"])
            self.assertTrue(snap_path.exists())
            self.assertTrue(sha_path.exists())
            self.assertEqual(pack["uia_ref"]["content_hash"], pack["snapshot"]["content_hash"])

    def test_mismatch_mode_sets_ref_hash_different_than_snapshot(self) -> None:
        mod = _load_module()
        pack = mod.build_contract_pack(
            run_id="run_c",
            uia_record_id="run_c/uia/0",
            ts_utc="2026-02-19T00:00:00Z",
            hash_mode="mismatch",
            focus_nodes=1,
            context_nodes=1,
            operable_nodes=1,
        )
        self.assertNotEqual(pack["uia_ref"]["content_hash"], pack["snapshot"]["content_hash"])


if __name__ == "__main__":
    unittest.main()
