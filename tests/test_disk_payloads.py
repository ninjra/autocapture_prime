import unittest

from plugins.builtin.capture_windows.plugin import CaptureWindows
from autocapture_nx.plugin_system.api import PluginContext


class _Logger:
    def __init__(self) -> None:
        self.records = []

    def log(self, event: str, payload: dict) -> None:
        self.records.append((event, payload))


class _Journal:
    def __init__(self) -> None:
        self.entries = []

    def append(self, entry: dict) -> None:
        self.entries.append(entry)


class _Ledger:
    def __init__(self) -> None:
        self.entries = []

    def append(self, entry: dict) -> str:
        self.entries.append(entry)
        return "hash"


class _Anchor:
    def anchor(self, _hash: str) -> None:
        return None


class _EventBuilder:
    def __init__(self) -> None:
        self.journal_payloads = []
        self.ledger_payloads = []

    def journal_event(self, _event_type: str, payload: dict, **_kwargs) -> str:
        self.journal_payloads.append(payload)
        return "event_id"

    def ledger_entry(self, _stage: str, inputs: list[str], outputs: list[str], *, payload: dict | None = None, **_kwargs) -> str:
        self.ledger_payloads.append(payload or {})
        return "hash"


class DiskPayloadTests(unittest.TestCase):
    def test_disk_payloads_are_integers(self) -> None:
        logger = _Logger()
        journal = _Journal()
        ledger = _Ledger()
        anchor = _Anchor()
        event_builder = _EventBuilder()

        config = {"storage": {"data_dir": "."}}
        ctx = PluginContext(config=config, get_capability=lambda _k: None, logger=lambda _m: None)
        plugin = CaptureWindows("capture", ctx)

        import shutil

        original = shutil.disk_usage
        try:
            shutil.disk_usage = lambda _path: (0, 0, 512 * 1024 * 1024)  # 0.5 GB free
            ok = plugin._check_disk(logger, event_builder, warn_free=200, critical_free=50)
        finally:
            shutil.disk_usage = original

        self.assertFalse(ok)
        self.assertTrue(event_builder.journal_payloads)
        self.assertTrue(event_builder.ledger_payloads)
        payload = event_builder.journal_payloads[0]
        self.assertIsInstance(payload["free_gb"], int)
        self.assertIsInstance(payload["threshold_gb"], int)


if __name__ == "__main__":
    unittest.main()
