import sys
import unittest
from unittest.mock import patch


def _fake_pytesseract(calls: list[dict]) -> object:
    class _Output:
        DICT = object()

    class _Fake:
        Output = _Output

        @staticmethod
        def image_to_data(_image, **kwargs):
            calls.append(dict(kwargs))
            return {
                "text": ["Inbox"],
                "conf": ["100"],
                "left": [0],
                "top": [0],
                "width": [10],
                "height": [10],
            }

    return _Fake()


class OCRBasicTesseractKwargsTests(unittest.TestCase):
    def test_tesseract_tokens_omits_none_lang_and_config(self) -> None:
        from autocapture.ingest import ocr_basic

        calls: list[dict] = []
        with patch.dict(sys.modules, {"pytesseract": _fake_pytesseract(calls)}):
            class _FakeImage:
                size = (100, 100)

            image = _FakeImage()
            toks = ocr_basic._tesseract_tokens(image, lang=None, psm=None, oem=None, tesseract_cmd=None)
        self.assertIsNotNone(toks)
        self.assertEqual(len(calls), 1)
        kwargs = calls[0]
        self.assertNotIn("lang", kwargs)
        self.assertNotIn("config", kwargs)

    def test_tesseract_tokens_passes_lang_and_config_when_set(self) -> None:
        from autocapture.ingest import ocr_basic

        calls: list[dict] = []
        with patch.dict(sys.modules, {"pytesseract": _fake_pytesseract(calls)}):
            class _FakeImage:
                size = (100, 100)

            image = _FakeImage()
            toks = ocr_basic._tesseract_tokens(image, lang="eng", psm=6, oem=3, tesseract_cmd=None)
        self.assertIsNotNone(toks)
        self.assertEqual(len(calls), 1)
        kwargs = calls[0]
        self.assertEqual(kwargs.get("lang"), "eng")
        self.assertIn("--psm 6", kwargs.get("config", ""))
        self.assertIn("--oem 3", kwargs.get("config", ""))


if __name__ == "__main__":
    unittest.main()
