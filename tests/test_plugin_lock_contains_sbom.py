from __future__ import annotations

from autocapture_nx.kernel.loader import default_config_paths
from autocapture_nx.kernel.config import load_config
from autocapture_nx.plugin_system.manager import PluginManager


def test_update_plugin_locks_includes_sbom_block():
    cfg = load_config(default_config_paths(), safe_mode=False)
    manager = PluginManager(cfg, safe_mode=False)
    lock = manager.approve_hashes()
    plugins = lock.get("plugins", {})
    assert isinstance(plugins, dict)
    assert plugins  # repo has plugins
    for _pid, entry in plugins.items():
        assert isinstance(entry, dict)
        assert "sbom" in entry
        sbom = entry["sbom"]
        assert isinstance(sbom, dict)
        assert "requirements" in sbom
        assert "requirements_sha256" in sbom
