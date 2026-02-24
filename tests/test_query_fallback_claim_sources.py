from __future__ import annotations

import unittest

from autocapture_nx.kernel import query as query_mod


class QueryFallbackClaimSourcesTests(unittest.TestCase):
    def test_signal_topic_skips_vlm_lookup(self) -> None:
        class _Metadata:
            def latest(self, *, record_type: str, limit: int = 256):  # noqa: ARG002
                if record_type == "derived.text.vlm":
                    raise AssertionError("signal_topic_must_not_scan_vlm_rows")
                if record_type != "derived.sst.text.extra":
                    return []
                return [
                    {
                        "record_id": "rec_song_1",
                        "record": {
                            "record_type": "derived.sst.text.extra",
                            "doc_kind": "obs.media.now_playing",
                            "provider_id": "builtin.observation.graph",
                            "source_id": "src_song_1",
                            "text": "Observation: current_song=Jimi Hendrix - Purple Haze",
                            "meta": {},
                        },
                    }
                ][: max(0, int(limit))]

            def get(self, _record_id: str):  # noqa: ANN001
                return None

        rows = query_mod._fallback_claim_sources_for_topic("song", _Metadata())
        self.assertTrue(rows)
        meta = query_mod._claim_doc_meta(rows[0])
        self.assertEqual(str(meta.get("source_modality") or ""), "ocr")
        self.assertEqual(str(meta.get("source_state_id") or ""), "ocr")

    def test_augment_display_sources_merges_fallback_signal_pairs(self) -> None:
        record_id = "rid_adv_1"

        class _Metadata:
            def latest(self, *, record_type: str, limit: int = 256):  # noqa: ARG002
                if record_type != "derived.sst.text.extra":
                    return []
                return [
                    {
                        "record_id": record_id,
                        "record": {
                            "record_type": "derived.sst.text.extra",
                            "doc_kind": "adv.window.inventory",
                            "provider_id": "builtin.processing.sst.pipeline",
                            "source_id": "src_adv_1",
                            "text": (
                                "Observation: adv.window.count=2; "
                                "adv.window.1.app=Outlook VDI; "
                                "adv.window.1.context=vdi; "
                                "adv.window.2.app=Slack; "
                                "adv.window.2.context=host"
                            ),
                            "meta": {},
                        },
                    }
                ][: max(0, int(limit))]

            def get(self, _record_id: str):  # noqa: ANN001
                return None

        base_sources = [
            {
                "record_id": record_id,
                "doc_kind": "adv.window.inventory",
                "provider_id": "builtin.observation.graph",
                "signal_pairs": {},
                "meta": {},
            }
        ]
        merged = query_mod._augment_claim_sources_for_display("adv_window_inventory", base_sources, _Metadata())
        self.assertTrue(merged)
        pairs = merged[0].get("signal_pairs", {}) if isinstance(merged[0].get("signal_pairs", {}), dict) else {}
        self.assertEqual(str(pairs.get("adv.window.count") or ""), "2")
        self.assertEqual(str(pairs.get("adv.window.1.app") or ""), "Outlook VDI")


if __name__ == "__main__":
    unittest.main()
