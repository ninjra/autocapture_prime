import json
import tempfile
import unittest
from pathlib import Path

from tools.gate_full_repo_miss_matrix import main as gate_main


class GateFullRepoMissMatrixTests(unittest.TestCase):
    def _write_inventory(self, path: Path, *, rows_total: int, gate_failures_total: int) -> None:
        payload = {
            "summary": {
                "rows_total": int(rows_total),
                "gate_failures_total": int(gate_failures_total),
            },
            "rows": [],
            "gate_failures": [],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_gate_passes_when_zero_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inv = Path(tmp) / "inventory.json"
            self._write_inventory(inv, rows_total=0, gate_failures_total=0)
            rc = gate_main(["--inventory-json", str(inv)])
            self.assertEqual(rc, 0)

    def test_gate_fails_when_rows_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inv = Path(tmp) / "inventory.json"
            self._write_inventory(inv, rows_total=1, gate_failures_total=0)
            rc = gate_main(["--inventory-json", str(inv)])
            self.assertEqual(rc, 1)

    def test_gate_fails_when_gate_failures_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inv = Path(tmp) / "inventory.json"
            self._write_inventory(inv, rows_total=0, gate_failures_total=1)
            rc = gate_main(["--inventory-json", str(inv)])
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
