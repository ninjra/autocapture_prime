import unittest

from autocapture_nx.plugin_system.api import PluginContext
from autocapture_nx.state_layer.evidence_compiler import EvidenceCompiler
from autocapture_nx.state_layer.policy_gate import StatePolicyDecision
from autocapture_nx.kernel.ids import encode_record_id_component


class _MetadataStore:
    def __init__(self):
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def keys(self):
        return list(self.data.keys())


class EvidenceCompilerTests(unittest.TestCase):
    def _compiler(self):
        config = {
            "processing": {
                "state_layer": {
                    "evidence": {
                        "max_hits": 5,
                        "max_evidence_per_hit": 3,
                        "max_snippets_per_hit": 2,
                        "max_snippet_chars": 100,
                    }
                }
            }
        }
        ctx = PluginContext(
            config=config,
            get_capability=lambda _name: None,
            logger=lambda *_args, **_kwargs: None,
            rng=None,
            rng_seed=None,
            rng_seed_hex=None,
        )
        return EvidenceCompiler("test.compiler", ctx)

    def test_compiler_includes_snippet_when_allowed(self):
        metadata = _MetadataStore()
        frame_id = "run/frame/1"
        state_id = "state1"
        state_record_id = "run/derived.sst.state/rid_state1"
        metadata.data[state_record_id] = {
            "record_type": "derived.sst.state",
            "run_id": "run",
            "screen_state": {
                "state_id": state_id,
                "frame_id": frame_id,
                "ts_ms": 1234,
                "tokens": [{"text": "Hello", "norm_text": "hello", "bbox": (0, 0, 1, 1)}],
            },
        }
        doc_id = f"run/derived.sst.text/state/{encode_record_id_component(state_id)}"
        metadata.data[doc_id] = {
            "record_type": "derived.sst.text",
            "text": "Hello World",
        }
        hit = {
            "state_id": "span1",
            "score": 0.9,
            "ts_start_ms": 1200,
            "ts_end_ms": 1300,
            "evidence": [
                {
                    "media_id": frame_id,
                    "ts_start_ms": 1200,
                    "ts_end_ms": 1200,
                    "frame_index": 0,
                    "bbox_xywh": [0, 0, 1, 1],
                    "text_span": {"start": 0, "end": 0},
                    "sha256": "aa",
                    "redaction_applied": False,
                }
            ],
            "provenance": {"input_artifact_ids": [state_record_id]},
        }
        compiler = self._compiler()
        policy = StatePolicyDecision(True, True, False, (), ())
        bundle = compiler.compile(query_id="q1", hits=[hit], policy=policy, metadata=metadata)
        snippets = bundle["hits"][0]["extracted_text_snippets"]
        self.assertTrue(snippets)
        self.assertEqual(snippets[0]["text"], "Hello World")

    def test_compiler_respects_policy(self):
        compiler = self._compiler()
        policy = StatePolicyDecision(False, False, False, (), ())
        bundle = compiler.compile(query_id="q2", hits=[], policy=policy, metadata=None)
        self.assertEqual(bundle["hits"], [])
        self.assertFalse(bundle["policy"]["can_export_text"])

    def test_compiler_orders_evidence(self):
        compiler = self._compiler()
        policy = StatePolicyDecision(True, False, False, (), ())
        hit = {
            "state_id": "span1",
            "score": 0.9,
            "ts_start_ms": 1200,
            "ts_end_ms": 1300,
            "evidence": [
                {
                    "media_id": "run/frame/2",
                    "ts_start_ms": 1300,
                    "ts_end_ms": 1300,
                    "frame_index": 0,
                    "bbox_xywh": [0, 0, 1, 1],
                    "text_span": {"start": 0, "end": 0},
                    "sha256": "bb",
                    "redaction_applied": False,
                },
                {
                    "media_id": "run/frame/1",
                    "ts_start_ms": 1200,
                    "ts_end_ms": 1200,
                    "frame_index": 0,
                    "bbox_xywh": [0, 0, 1, 1],
                    "text_span": {"start": 0, "end": 0},
                    "sha256": "aa",
                    "redaction_applied": False,
                },
            ],
            "provenance": {"input_artifact_ids": []},
        }
        bundle = compiler.compile(query_id="q3", hits=[hit], policy=policy, metadata=None)
        evidence = bundle["hits"][0]["evidence"]
        self.assertEqual(evidence[0]["media_id"], "run/frame/1")


if __name__ == "__main__":
    unittest.main()
