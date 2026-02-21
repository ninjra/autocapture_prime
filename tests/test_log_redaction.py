from __future__ import annotations

from pathlib import Path

from autocapture_nx.kernel.logging import JsonlLogger


def test_jsonl_logger_redacts_common_secret_patterns(tmp_path) -> None:
    cfg = {"storage": {"data_dir": str(tmp_path)}}
    logger = JsonlLogger.from_config(cfg, name="test")
    logger.event(event="test", run_id="run", token="sk-abcdefghijklmnopqrstuvwxyz0123456789", auth="Bearer abc.def.ghi")
    path = Path(logger.path)
    text = path.read_text(encoding="utf-8")
    assert "sk-" not in text
    assert "Bearer " not in text
    assert "[REDACTED]" in text

