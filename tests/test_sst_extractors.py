import unittest

from autocapture_nx.processing.sst.extract import extract_code_blocks, extract_spreadsheets, extract_tables
from autocapture_nx.processing.sst.layout import assemble_layout


def _token(token_id: str, text: str, bbox: tuple[int, int, int, int]) -> dict:
    return {
        "token_id": token_id,
        "text": text,
        "norm_text": text.strip(),
        "bbox": bbox,
        "confidence_bp": 9000,
        "source": "ocr",
        "flags": {"monospace_likely": False, "is_number": text.isdigit()},
    }


class SSTExtractorTests(unittest.TestCase):
    def test_code_blocks_strip_line_numbers(self) -> None:
        tokens = [
            _token("t1", "1", (0, 0, 8, 10)),
            _token("t2", "SELECT", (20, 0, 80, 10)),
            _token("t3", "2", (0, 20, 8, 30)),
            _token("t4", "FROM", (20, 20, 60, 30)),
        ]
        lines, _blocks = assemble_layout(tokens, line_y_threshold_px=12, block_gap_px=24, align_tolerance_px=20)
        code_blocks = extract_code_blocks(tokens=tokens, text_lines=lines, state_id="s1", min_keywords=1)
        self.assertTrue(code_blocks)
        code = code_blocks[0]
        self.assertEqual(tuple(line.lstrip() for line in code["lines"]), ("SELECT", "FROM"))
        self.assertEqual(code["line_numbers"], ("1", "2"))

    def test_spreadsheet_active_cell_and_formula_bar(self) -> None:
        tokens = [
            _token("fx", "fx", (10, 0, 20, 10)),
            _token("colA", "A", (30, 0, 40, 10)),
            _token("colB", "B", (60, 0, 70, 10)),
            _token("row1", "1", (0, 20, 10, 30)),
            _token("row2", "2", (0, 40, 10, 50)),
            _token("a1", "alpha", (30, 20, 50, 30)),
            _token("b1", "beta", (60, 20, 80, 30)),
            _token("a2", "gamma", (30, 40, 50, 50)),
            _token("b2", "delta", (60, 40, 80, 50)),
            _token("ref", "A1", (5, 5, 20, 15)),
        ]
        tables = extract_tables(tokens=tokens, state_id="s1", min_rows=2, min_cols=2, max_cells=50, row_gap_px=12, col_gap_px=24)
        self.assertTrue(tables)
        self.assertIn("tsv", tables[0])
        sheets = extract_spreadsheets(tokens=tokens, tables=tables, state_id="s1", header_scan_rows=1)
        self.assertTrue(sheets)
        sheet = sheets[0]
        self.assertIsNotNone(sheet.get("active_cell"))
        self.assertIsNotNone(sheet.get("formula_bar"))
        self.assertIn("A", sheet.get("header_map", {}).values())


if __name__ == "__main__":
    unittest.main()
