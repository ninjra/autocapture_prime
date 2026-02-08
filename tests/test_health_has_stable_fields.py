from __future__ import annotations

import unittest

from autocapture_nx.kernel.doctor import build_health_report


class _Caps:
    def __init__(self, items: dict) -> None:
        self._items = dict(items)

    def all(self) -> dict:
        return dict(self._items)


class _System:
    def __init__(self, caps: dict) -> None:
        self.capabilities = _Caps(caps)


class _Check:
    def __init__(self, name: str, ok: bool, detail: str) -> None:
        self.name = name
        self.ok = ok
        self.detail = detail


class HealthStableFieldsTests(unittest.TestCase):
    def test_health_has_stable_summary_fields(self) -> None:
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
        checks = [_Check("instance_lock", True, "ok")]
        payload = build_health_report(system=system, checks=checks)
        self.assertIn("ok", payload)
        self.assertIn("generated_at_utc", payload)
        self.assertIn("summary", payload)
        self.assertIn("components", payload)
        summary = payload.get("summary")
        self.assertIsInstance(summary, dict)
        for key in ("ok", "components_total", "components_ok", "checks_total", "checks_failed"):
            self.assertIn(key, summary)


if __name__ == "__main__":
    unittest.main()

