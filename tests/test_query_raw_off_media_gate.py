from __future__ import annotations

import unittest

from autocapture_nx.kernel import query as query_mod


class _Media:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls = 0

    def get(self, _record_id: str) -> bytes:
        self.calls += 1
        return self.payload


class _Metadata:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row

    def get(self, _record_id: str, default=None):  # noqa: ANN001
        return dict(self.row) if self.row else (default if default is not None else {})


class _System:
    def __init__(self, *, raw_off_enabled: bool | None, media: _Media, metadata: _Metadata) -> None:
        self.config = {}
        if raw_off_enabled is not None:
            self.config = {"runtime": {"raw_off": {"enabled": raw_off_enabled}}}
        self._cap = {
            "storage.media": media,
            "storage.metadata": metadata,
        }

    def get(self, key: str):
        return self._cap.get(key)


class QueryRawOffMediaGateTests(unittest.TestCase):
    def test_raw_off_defaults_to_enabled_and_blocks_raw_media_reads(self) -> None:
        query_mod._reset_query_contract_counters_for_tests()
        media = _Media(
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\x99c````\x00\x00\x00\x04\x00\x01"
            b"\x0b\xe7\x02\x9d\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        metadata = _Metadata({"record_type": "evidence.capture.frame", "container": {"type": "zip"}})
        system = _System(raw_off_enabled=None, media=media, metadata=metadata)

        blob = query_mod._load_evidence_image_bytes(system, "run/evidence.capture.frame/1")

        self.assertEqual(blob, b"")
        self.assertEqual(media.calls, 0)
        counters = query_mod._query_contract_counter_snapshot()
        self.assertEqual(int(counters.get("query_raw_media_reads_total", -1)), 0)

    def test_raw_off_false_still_blocks_raw_media_reads(self) -> None:
        query_mod._reset_query_contract_counters_for_tests()
        payload = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\x99c````\x00\x00\x00\x04\x00\x01"
            b"\x0b\xe7\x02\x9d\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        media = _Media(payload)
        metadata = _Metadata({"record_type": "evidence.capture.frame", "container": {"type": "zip"}})
        system = _System(raw_off_enabled=False, media=media, metadata=metadata)

        blob = query_mod._load_evidence_image_bytes(system, "run/evidence.capture.frame/1")

        self.assertEqual(blob, b"")
        self.assertEqual(media.calls, 0)
        counters = query_mod._query_contract_counter_snapshot()
        self.assertEqual(int(counters.get("query_raw_media_reads_total", 0)), 0)


if __name__ == "__main__":
    unittest.main()
