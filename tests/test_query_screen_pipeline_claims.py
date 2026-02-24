import io
import unittest
import zipfile

from autocapture_nx.kernel.query import _run_screen_pipeline_custom_claims


class _FakeMetadata:
    def __init__(self) -> None:
        self.rows = {
            "run/evidence.capture.frame/1": {
                "record_type": "evidence.capture.frame",
                "content_hash": "evidence_hash_1",
                "container": {"type": "zip"},
            }
        }

    def get(self, record_id: str, default=None):  # noqa: ANN001
        return self.rows.get(record_id, default if default is not None else {})

    def put_new(self, record_id: str, payload):  # noqa: ANN001
        self.rows[record_id] = payload


class _FakeMedia:
    def __init__(self) -> None:
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\x99c````\x00\x00\x00\x04\x00\x01"
            b"\x0b\xe7\x02\x9d\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        buff = io.BytesIO()
        with zipfile.ZipFile(buff, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("frame.png", png)
        self._payload = buff.getvalue()

    def get(self, record_id: str):  # noqa: ANN001
        if str(record_id).endswith("evidence.capture.frame/1"):
            return self._payload
        return b""


class _FakeParse:
    plugin_id = "builtin.screen.parse.v1"

    def parse(self, image_bytes: bytes, *, frame_id: str = "", layout=None):  # noqa: ANN001
        return {
            "schema_version": 1,
            "frame_id": frame_id,
            "nodes": [
                {
                    "node_id": "node_1",
                    "kind": "label",
                    "text": "Open inboxes 4",
                    "bbox": [10, 10, 100, 30],
                    "children": [],
                }
            ],
            "edges": [],
            "root_nodes": ["node_1"],
        }


class _FakeIndex:
    plugin_id = "builtin.screen.index.v1"

    def index(self, ui_graph, *, frame_id: str = ""):  # noqa: ANN001
        return {
            "schema_version": 1,
            "frame_id": frame_id,
            "chunks": [
                {
                    "chunk_id": "chunk_1",
                    "node_id": "node_1",
                    "text": "Open inboxes 4",
                    "terms": ["open", "inboxes", "4"],
                    "bbox": [10, 10, 100, 30],
                    "embedding": [],
                    "evidence_id": "evidence_1",
                }
            ],
            "evidence": [
                {
                    "evidence_id": "evidence_1",
                    "type": "ui_node",
                    "source": {"frame_id": frame_id, "node_id": "node_1"},
                    "bbox": [10, 10, 100, 30],
                    "hash": "hash_1",
                }
            ],
        }


class _FakeAnswer:
    plugin_id = "builtin.screen.answer.v1"

    def answer(self, query: str, indexed, *, max_claims: int = 4):  # noqa: ANN001
        return {
            "state": "ok",
            "summary": "Open inboxes: 4",
            "claims": [
                {
                    "text": "Open inboxes: 4",
                    "citations": [
                        {
                            "evidence_id": "evidence_1",
                            "source": {"frame_id": "run/evidence.capture.frame/1", "node_id": "node_1"},
                            "bbox": [10, 10, 100, 30],
                        }
                    ],
                }
            ],
            "errors": [],
        }


class _FakeSystem:
    def __init__(self) -> None:
        self.config = {"runtime": {"raw_off": {"enabled": False}}, "query": {"screen_pipeline": {"enabled": True}}}
        self._cap = {
            "screen.parse.v1": _FakeParse(),
            "screen.index.v1": _FakeIndex(),
            "screen.answer.v1": _FakeAnswer(),
            "storage.media": _FakeMedia(),
        }

    def get(self, name: str):
        return self._cap.get(name)


class QueryScreenPipelineClaimsTests(unittest.TestCase):
    def test_raw_off_false_disables_query_time_screen_pipeline(self) -> None:
        system = _FakeSystem()
        metadata = _FakeMetadata()
        claims, debug, err = _run_screen_pipeline_custom_claims(
            system,
            query_text="how many inboxes",
            evidence_ids=["run/evidence.capture.frame/1"],
            metadata=metadata,
            query_ledger_hash="ledger123",
            anchor_ref="anchor123",
        )
        self.assertIsNone(err)
        self.assertEqual(claims, [])
        self.assertFalse(bool(debug.get("enabled")))
        self.assertEqual(str(debug.get("reason") or ""), "raw_off_enforced")

    def test_raw_off_default_disables_query_time_screen_pipeline(self) -> None:
        class _RawOffSystem(_FakeSystem):
            def __init__(self) -> None:
                super().__init__()
                self.config = {"query": {"screen_pipeline": {"enabled": True}}}

        system = _RawOffSystem()
        metadata = _FakeMetadata()
        claims, debug, err = _run_screen_pipeline_custom_claims(
            system,
            query_text="how many inboxes",
            evidence_ids=["run/evidence.capture.frame/1"],
            metadata=metadata,
            query_ledger_hash="ledger123",
            anchor_ref="anchor123",
        )
        self.assertIsNone(err)
        self.assertEqual(claims, [])
        self.assertFalse(bool(debug.get("enabled")))
        self.assertEqual(str(debug.get("reason") or ""), "raw_off_enforced")


if __name__ == "__main__":
    unittest.main()
