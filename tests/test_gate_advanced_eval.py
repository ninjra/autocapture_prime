from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


def _load_module():
    path = pathlib.Path("tools/gate_advanced_eval.py")
    spec = importlib.util.spec_from_file_location("gate_advanced_eval_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GateAdvancedEvalTests(unittest.TestCase):
    def test_gate_passes_when_all_constraints_met(self) -> None:
        mod = _load_module()
        rows = [{"expected_eval": {"evaluated": True, "passed": True}} for _ in range(4)]
        with tempfile.TemporaryDirectory() as tmp:
            artifact = pathlib.Path(tmp) / "artifact.json"
            artifact.write_text(json.dumps({"rows": rows}), encoding="utf-8")
            rc = mod.main(
                [
                    "--artifact",
                    str(artifact),
                    "--require-total",
                    "4",
                    "--require-evaluated",
                    "4",
                    "--max-failed",
                    "0",
                ]
            )
        self.assertEqual(rc, 0)

    def test_gate_fails_when_evaluated_missing(self) -> None:
        mod = _load_module()
        rows = [
            {"expected_eval": {"evaluated": True, "passed": True}},
            {"expected_eval": {"evaluated": False, "passed": None}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            artifact = pathlib.Path(tmp) / "artifact.json"
            artifact.write_text(json.dumps({"rows": rows}), encoding="utf-8")
            rc = mod.main(
                [
                    "--artifact",
                    str(artifact),
                    "--require-total",
                    "2",
                    "--require-evaluated",
                    "2",
                    "--max-failed",
                    "0",
                ]
            )
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()

