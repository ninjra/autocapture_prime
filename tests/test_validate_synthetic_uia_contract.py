from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load_module(path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, Path(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ValidateSyntheticUIAContractTests(unittest.TestCase):
    def test_validate_pack_passes_for_valid_pack(self) -> None:
        pack_mod = _load_module("tools/synthetic_uia_contract_pack.py", "synthetic_pack_tool")
        val_mod = _load_module("tools/validate_synthetic_uia_contract.py", "validate_pack_tool")
        with tempfile.TemporaryDirectory() as tmp:
            result = pack_mod.write_contract_pack(
                out_dir=Path(tmp),
                run_id="run_ok",
                uia_record_id="run_ok/uia/0",
                ts_utc="2026-02-19T00:00:00Z",
                hash_mode="match",
                focus_nodes=2,
                context_nodes=2,
                operable_nodes=2,
                write_hash_file=True,
            )
            pack_path = Path(result["pack_path"])
            pack = json.loads(pack_path.read_text(encoding="utf-8"))
            errors = val_mod.validate_pack(pack, require_hash_match=True)
            self.assertEqual(errors, [])

    def test_validate_pack_rejects_hash_mismatch_when_required(self) -> None:
        pack_mod = _load_module("tools/synthetic_uia_contract_pack.py", "synthetic_pack_tool2")
        val_mod = _load_module("tools/validate_synthetic_uia_contract.py", "validate_pack_tool2")
        with tempfile.TemporaryDirectory() as tmp:
            result = pack_mod.write_contract_pack(
                out_dir=Path(tmp),
                run_id="run_bad",
                uia_record_id="run_bad/uia/0",
                ts_utc="2026-02-19T00:00:00Z",
                hash_mode="mismatch",
                focus_nodes=1,
                context_nodes=1,
                operable_nodes=1,
                write_hash_file=True,
            )
            pack = json.loads(Path(result["pack_path"]).read_text(encoding="utf-8"))
            errors = val_mod.validate_pack(pack, require_hash_match=True)
            self.assertIn("uia_ref_snapshot_hash_mismatch", errors)
            self.assertIn("fallback_sha256_file_mismatch", errors)

    def test_validate_pack_missing_required_fields_fails(self) -> None:
        val_mod = _load_module("tools/validate_synthetic_uia_contract.py", "validate_pack_tool3")
        bad_pack = {
            "uia_ref": {"record_id": "", "ts_utc": "", "content_hash": ""},
            "snapshot": {"record_type": "bad"},
            "metadata_record": {},
            "fallback": {"latest_snap_json": "", "latest_snap_sha256": "", "latest_snap_file_hash": ""},
        }
        errors = val_mod.validate_pack(bad_pack, require_hash_match=True)
        self.assertIn("uia_ref_missing_record_id", errors)
        self.assertIn("snapshot_record_type_invalid", errors)
        self.assertIn("metadata_record_type_invalid", errors)
        self.assertIn("fallback_latest_snap_json_missing", errors)


if __name__ == "__main__":
    unittest.main()
