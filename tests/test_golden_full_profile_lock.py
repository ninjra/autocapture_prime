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
