from __future__ import annotations

import json
from pathlib import Path


def test_stage1_no_vlm_profile_contract() -> None:
    profile = json.loads(Path("config/profiles/stage1_no_vlm_idle.json").read_text(encoding="utf-8"))
    idle = profile.get("processing", {}).get("idle", {})
    assert bool(idle.get("extractors", {}).get("ocr", False)) is True
    assert bool(idle.get("extractors", {}).get("vlm", True)) is False
    assert int(idle.get("max_concurrency_cpu", 0) or 0) >= 1
    assert int(idle.get("batch_size", 0) or 0) >= int(idle.get("max_concurrency_cpu", 1) or 1)
    assert int(idle.get("max_items_per_run", 0) or 0) >= int(idle.get("batch_size", 1) or 1)
    adaptive = idle.get("adaptive_parallelism", {})
    assert bool(adaptive.get("enabled", False)) is True
    assert int(adaptive.get("cpu_max", 0) or 0) >= int(adaptive.get("cpu_min", 1) or 1)

    sst = profile.get("processing", {}).get("sst", {})
    assert bool(sst.get("allow_ocr", False)) is True
    assert bool(sst.get("allow_vlm", True)) is False

    on_query = profile.get("processing", {}).get("on_query", {})
    assert bool(on_query.get("allow_decode_extract", True)) is False
    assert bool(on_query.get("extractors", {}).get("ocr", True)) is False
    assert bool(on_query.get("extractors", {}).get("vlm", True)) is False
    assert bool(on_query.get("require_idle", False)) is True
