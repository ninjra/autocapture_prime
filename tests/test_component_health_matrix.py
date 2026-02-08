from __future__ import annotations

import unittest

from autocapture_nx.kernel.doctor import build_component_matrix


class _Caps:
    def __init__(self, items: dict) -> None:
        self._items = dict(items)

    def all(self) -> dict:
        return dict(self._items)


class _System:
    def __init__(self, caps: dict) -> None:
        self.capabilities = _Caps(caps)


class _Check:
    def __init__(self, name: str, ok: bool) -> None:
        self.name = name
        self.ok = ok


class ComponentHealthMatrixTests(unittest.TestCase):
    def test_component_matrix_includes_pipeline_components(self) -> None:
        system = _System(
            {
                "capture.source": object(),
                "ocr.engine": object(),
                "vision.extractor": object(),
                "embedder.text": object(),
                "retrieval.strategy": object(),
                "answer.builder": object(),
                "citation.validator": object(),
                "storage.metadata": object(),
                "storage.media": object(),
                "ledger.writer": object(),
                "journal.writer": object(),
                "anchor.writer": object(),
            }
        )
        checks = [_Check("instance_lock", True)]
        matrix = build_component_matrix(system=system, checks=checks)
        names = {item.name for item in matrix}
        for required in ("capture", "ocr", "vlm", "indexing", "retrieval", "answer"):
            self.assertIn(required, names)


if __name__ == "__main__":
    unittest.main()

