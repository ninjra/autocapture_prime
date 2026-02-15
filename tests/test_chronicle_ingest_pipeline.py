from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from autocapture_prime.config import load_prime_config
from autocapture_prime.ingest.pipeline import ingest_one_session
from autocapture_prime.ingest.session_scanner import SessionCandidate


def _read_rows(path: Path) -> list[dict]:
    if path.suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
        except Exception:
            return []
        table = pq.read_table(path)
        return [row for row in table.to_pylist() if isinstance(row, dict)]
    rows: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


class ChronicleIngestPipelineTests(unittest.TestCase):
    def test_ingest_emits_tables(self) -> None:
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
                    ]
                ),
                encoding="utf-8",
            )
            cfg = load_prime_config(cfg_path)
            summary = ingest_one_session(candidate, cfg)
            self.assertEqual(summary.get("session_id"), "test-0001")
            rows = summary.get("rows", {})
            self.assertGreaterEqual(int(rows.get("frames", 0)), 2)
            out = Path(summary["outputs"]["frames"])
            self.assertTrue(out.exists())
            self.assertGreaterEqual(int(summary.get("click_anchor_frames", 0)), 1)
            ingest_metrics = Path(td) / "out" / "metrics" / "ingest_metrics.ndjson"
            self.assertTrue(ingest_metrics.exists())

            ocr_table = _read_rows(Path(summary["outputs"]["ocr_spans"]))
            self.assertTrue(any("extractor" in row for row in ocr_table))
            self.assertTrue(any("source_pass" in row for row in ocr_table))

            tracks_table = _read_rows(Path(summary["outputs"]["tracks"]))
            self.assertTrue(any("anchor_used" in row for row in tracks_table))


if __name__ == "__main__":
    unittest.main()
