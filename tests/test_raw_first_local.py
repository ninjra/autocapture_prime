import unittest

from autocapture_nx.processing.sst.pipeline import _sst_config


class RawFirstLocalTests(unittest.TestCase):
    def test_raw_first_disables_redaction(self) -> None:
        cfg = {
            "storage": {"raw_first_local": True},
            "processing": {"sst": {"redact_enabled": True}},
        }
        sst_cfg = _sst_config(cfg)
        self.assertFalse(bool(sst_cfg.get("redact_enabled")))
        stage = sst_cfg.get("stage_providers", {}).get("compliance.redact", {})
        if isinstance(stage, dict):
            self.assertFalse(bool(stage.get("enabled", True)))


if __name__ == "__main__":
    unittest.main()
