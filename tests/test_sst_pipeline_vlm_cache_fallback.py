import unittest

from autocapture_nx.kernel.derived_records import derived_text_record_id
from autocapture_nx.processing.sst.pipeline import SSTPipeline


class _FailingVLMProvider:
    def extract(self, _frame_bytes: bytes):
        raise RuntimeError("offline")


class _MetadataStore:
    def __init__(self, rows: dict[str, dict]):
        self._rows = rows

    def get(self, key: str):
        return self._rows.get(key)


class SSTPipelineVLMCacheFallbackTests(unittest.TestCase):
    def test_vlm_tokens_uses_cached_derived_text_when_provider_unavailable(self) -> None:
        run_id = "run"
        source_id = "run/evidence.capture.frame/0"
        provider_id = "builtin.vlm.vllm_localhost"
        config = {"models": {}}
        derived_id = derived_text_record_id(
            kind="vlm",
            run_id=run_id,
            provider_id=provider_id,
            source_id=source_id,
            config=config,
        )
        pipeline = SSTPipeline.__new__(SSTPipeline)
        pipeline._vlm = {provider_id: _FailingVLMProvider()}  # type: ignore[attr-defined]
        pipeline._metadata = _MetadataStore(  # type: ignore[attr-defined]
            {derived_id: {"text": '{"elements":[{"type":"window","bbox":[0,0,100,100],"text":"Inbox"}]}'}}
        )
        pipeline._config = config  # type: ignore[attr-defined]

        tokens = pipeline._vlm_tokens(
            frame_width=100,
            frame_height=100,
            frame_bytes=b"img",
            allow_vlm=True,
            should_abort=None,
            deadline_ts=None,
            run_id=run_id,
            source_id=source_id,
        )
        self.assertEqual(len(tokens), 1)
        tok = tokens[0]
        self.assertEqual(tok.get("source"), "vlm")
        self.assertEqual(tok.get("provider_id"), provider_id)
        self.assertTrue(str(tok.get("text") or ""))


if __name__ == "__main__":
    unittest.main()
