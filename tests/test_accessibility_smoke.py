import unittest
from html.parser import HTMLParser
from pathlib import Path


class _TagScanner(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag, attrs):  # type: ignore[override]
        self.tags.append((tag, {k: (v or "") for k, v in attrs}))


class AccessibilitySmokeTests(unittest.TestCase):
    def test_ui_has_basic_a11y_affordances(self) -> None:
        path = Path("autocapture/web/ui/index.html")
        html = path.read_text(encoding="utf-8")
        parser = _TagScanner()
        parser.feed(html)

        # Skip link exists.
        anchors = [attrs for tag, attrs in parser.tags if tag == "a"]
        self.assertTrue(any(attrs.get("href", "").startswith("#") and "skip" in attrs.get("class", "") for attrs in anchors))

        # Main landmark exists.
        self.assertTrue(any(tag == "main" for tag, _ in parser.tags))


if __name__ == "__main__":
    unittest.main()

