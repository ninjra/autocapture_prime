from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _canonical_digest(path: Path) -> str:
    obj = json.loads(path.read_text(encoding="utf-8"))
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_golden_full_profile_hash_is_locked() -> None:
    profile = Path("config/profiles/golden_full.json")
    lock = Path("config/profiles/golden_full.sha256")
    assert profile.exists()
    assert lock.exists()
    expected = lock.read_text(encoding="utf-8").strip()
    assert expected
    assert _canonical_digest(profile) == expected


def test_golden_full_profile_required_plugins_present() -> None:
    profile = json.loads(Path("config/profiles/golden_full.json").read_text(encoding="utf-8"))
    plugins = profile.get("plugins", {}) if isinstance(profile, dict) else {}
    settings = plugins.get("settings", {}) if isinstance(plugins, dict) else {}
    golden = settings.get("__golden_profile", {}) if isinstance(settings, dict) else {}
    required = set(golden.get("required_plugins", []) if isinstance(golden, dict) else [])
    for plugin_id in (
        "builtin.processing.sst.pipeline",
        "builtin.processing.sst.ui_vlm",
        "builtin.vlm.vllm_localhost",
        "builtin.embedder.vllm_localhost",
        "builtin.index.colbert_hash",
        "builtin.reranker.colbert_hash",
        "builtin.state.jepa_like",
        "builtin.state.retrieval",
    ):
        assert plugin_id in required


def test_golden_profiles_option_a_metadata_and_retention_contract() -> None:
    full = json.loads(Path("config/profiles/golden_full.json").read_text(encoding="utf-8"))
    qh = json.loads(Path("config/profiles/golden_qh.json").read_text(encoding="utf-8"))

    # Metadata-only query contract: no query-time tactical image extraction or hard-VLM path.
    full_on_query = full.get("processing", {}).get("on_query", {})
    assert bool(full_on_query.get("allow_decode_extract", True)) is False
    assert bool(full_on_query.get("extractors", {}).get("ocr", True)) is False
    assert bool(full_on_query.get("extractors", {}).get("vlm", True)) is False
    assert bool(full.get("processing", {}).get("idle", {}).get("extractors", {}).get("ocr", True)) is False
    assert bool(full.get("processing", {}).get("idle", {}).get("extractors", {}).get("vlm", True)) is False
    golden = full.get("plugins", {}).get("settings", {}).get("__golden_profile", {})
    assert bool(golden.get("enable_synthesizer", True)) is False

    qh_on_query = qh.get("processing", {}).get("on_query", {})
    assert bool(qh_on_query.get("allow_decode_extract", True)) is False
    assert bool(qh_on_query.get("extractors", {}).get("ocr", True)) is False
    assert bool(qh_on_query.get("extractors", {}).get("vlm", True)) is False

    # Retention contract: processed-only image cleanup with 6-day horizon, nightly cadence.
    for profile in (full, qh):
        storage = profile.get("storage", {})
        retention = storage.get("retention", {})
        assert bool(storage.get("no_deletion_mode", True)) is False
        assert str(retention.get("evidence") or "") == "6d"
        assert bool(retention.get("processed_only", False)) is True
        assert bool(retention.get("images_only", False)) is True
        assert int(retention.get("interval_s", 0) or 0) == 86400
