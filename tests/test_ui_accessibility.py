import unittest
from html.parser import HTMLParser
from pathlib import Path


class _A11yParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.labels_for: set[str] = set()
        self.inputs: list[tuple[str, dict[str, str]]] = []
        self.buttons: list[dict[str, str]] = []
        self._current_button: dict[str, str] | None = None
        self._current_label_for: str | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_dict = {name: value for name, value in attrs if name}
        if tag == "label":
            self._current_label_for = attrs_dict.get("for")
        if tag in {"input", "textarea", "select"}:
            self.inputs.append((tag, attrs_dict))
        if tag == "button":
            self._current_button = {"text": "", **attrs_dict}
            self.buttons.append(self._current_button)

    def handle_data(self, data: str) -> None:
        if self._current_button is not None:
            self._current_button["text"] = (self._current_button.get("text") or "") + data.strip()
        if self._current_label_for:
            if data.strip():
                self.labels_for.add(self._current_label_for)

    def handle_endtag(self, tag: str) -> None:
        if tag == "label":
            self._current_label_for = None
        if tag == "button":
            self._current_button = None


class UiAccessibilityTests(unittest.TestCase):
    def test_interactive_elements_have_labels(self) -> None:
        html = Path("autocapture/web/ui/index.html").read_text(encoding="utf-8")
        parser = _A11yParser()
        parser.feed(html)

        for tag, attrs in parser.inputs:
            input_type = (attrs.get("type") or "").lower()
            if input_type in {"hidden"}:
                continue
            if attrs.get("aria-hidden") == "true":
                continue
            input_id = attrs.get("id")
            has_label = bool(input_id and input_id in parser.labels_for)
            has_aria = bool(attrs.get("aria-label") or attrs.get("aria-labelledby"))
            has_placeholder = bool(attrs.get("placeholder"))
            self.assertTrue(
                has_label or has_aria or has_placeholder,
                msg=f"{tag} missing label: {attrs}",
            )

        for button in parser.buttons:
            text = button.get("text", "").strip()
            has_label = bool(text or button.get("aria-label") or button.get("title"))
            self.assertTrue(has_label, msg=f"button missing label: {button}")


if __name__ == "__main__":
    unittest.main()
