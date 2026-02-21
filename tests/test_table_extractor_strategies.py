import tempfile
import unittest
import warnings

from autocapture.ingest.table_extractor import TableExtractor


class TableExtractorStrategiesTests(unittest.TestCase):
    def test_text_strategy(self) -> None:
        extractor = TableExtractor()
        rows = extractor.extract_from_text("a,b\n1,2")
        self.assertEqual(rows[0], ["a", "b"])

    def test_pdf_strategy(self) -> None:
        extractor = TableExtractor()
        writer_cls = None
        try:
            from pypdf import PdfWriter as writer_cls
        except Exception:
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=DeprecationWarning, module="PyPDF2")
                    from PyPDF2 import PdfWriter as writer_cls
            except Exception:
                self.skipTest("PDF writer not available")
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/test.pdf"
            writer = writer_cls()
            writer.add_blank_page(width=72, height=72)
            with open(path, "wb") as handle:
                writer.write(handle)
            rows = extractor.extract_from_pdf(path)
            self.assertIsInstance(rows, list)

    def test_image_strategy(self) -> None:
        extractor = TableExtractor()
        try:
            from PIL import Image, ImageDraw
        except Exception:
            self.skipTest("Pillow not available")
        img = Image.new("RGB", (100, 30), color="white")
        draw = ImageDraw.Draw(img)
        draw.text((0, 0), "a b", fill="black")
        try:
            rows = extractor.extract_from_image(img)
            self.assertIsInstance(rows, list)
        except RuntimeError:
            self.skipTest("OCR not available")


if __name__ == "__main__":
    unittest.main()
