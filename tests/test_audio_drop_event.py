import unittest

from plugins.builtin.audio_windows.plugin import _record_audio_drop


class _EventBuilder:
    def __init__(self) -> None:
        self.journal: list[tuple[str, dict]] = []
        self.ledger: list[tuple[str, dict]] = []

    def journal_event(self, event_type: str, payload: dict, **_kwargs) -> str:
        self.journal.append((event_type, payload))
        return "event"

    def ledger_entry(self, stage: str, inputs: list[str], outputs: list[str], *, payload: dict | None = None, **_kwargs) -> str:
        _ = (inputs, outputs)
        self.ledger.append((stage, payload or {}))
        return "hash"


class AudioDropEventTests(unittest.TestCase):
    def test_audio_drop_event_emitted(self) -> None:
        builder = _EventBuilder()
        payload = {"dropped": 3, "queue_max": 4, "policy": "drop_newest", "source": "loopback"}

        _record_audio_drop(builder, payload)

        self.assertEqual(builder.journal[0][0], "audio.drop")
        self.assertEqual(builder.ledger[0][0], "audio.drop")
        self.assertEqual(builder.journal[0][1]["dropped"], 3)


if __name__ == "__main__":
    unittest.main()
