from __future__ import annotations


def test_update_plugin_locks_includes_sbom_block():
    from tools.hypervisor.scripts.update_plugin_locks import update_plugin_locks

    lock = update_plugin_locks()
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

