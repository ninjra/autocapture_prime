"""Table extraction strategies."""

from __future__ import annotations

import csv
import warnings

from autocapture.ingest.ocr_basic import ocr_text_from_image


class TableExtractor:
    def _parse_text(self, text: str) -> list[list[str]]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return []
        if any("," in line for line in lines):
            reader = csv.reader(lines)
            return [row for row in reader]
        return [line.split() for line in lines]

    def extract_from_text(self, text: str) -> list[list[str]]:
        return self._parse_text(text)

    def extract_from_image(self, image) -> list[list[str]]:
        try:
            text = ocr_text_from_image(image)
        except Exception:
            text = ""
        return self._parse_text(text)

    def extract_from_pdf(self, path: str) -> list[list[str]]:
        reader_cls = None
        try:
            from pypdf import PdfReader as reader_cls
        except Exception:
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=DeprecationWarning, module="PyPDF2")
                    from PyPDF2 import PdfReader as reader_cls
            except Exception as exc:
                raise RuntimeError(f"PDF extraction unavailable: {exc}")
        reader = reader_cls(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return self._parse_text(text)


def create_table_extractor(plugin_id: str) -> TableExtractor:
    return TableExtractor()
