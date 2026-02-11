from __future__ import annotations

import unittest

from autocapture_nx.kernel.errors import PluginError
from autocapture_nx.plugin_system.registry import PluginRegistry


class LocalhostPluginPermissionsTests(unittest.TestCase):
    def _registry(self, *, internet: list[str] | None = None, localhost: list[str] | None = None) -> PluginRegistry:
        cfg = {
            "plugins": {
                "permissions": {
                    "network_allowed_plugin_ids": list(internet or []),
                    "localhost_allowed_plugin_ids": list(localhost or []),
                },
                "hosting": {"mode": "subprocess", "inproc_allowlist": []},
            },
            "storage": {"data_dir": "data"},
        }
        return PluginRegistry(cfg, safe_mode=False)

    def test_network_scope_internet_and_localhost(self) -> None:
        reg = self._registry(internet=["builtin.egress.gateway"], localhost=["builtin.vlm.vllm_localhost"])
        self.assertEqual(reg._network_scope_for_plugin("builtin.egress.gateway", network_requested=True), "internet")
        self.assertEqual(reg._network_scope_for_plugin("builtin.vlm.vllm_localhost", network_requested=True), "localhost")
        self.assertEqual(reg._network_scope_for_plugin("unknown.plugin", network_requested=True), "none")
        self.assertEqual(reg._network_scope_for_plugin("unknown.plugin", network_requested=False), "none")

    def test_check_permissions_allows_localhost_allowlist(self) -> None:
        reg = self._registry(localhost=["builtin.vlm.vllm_localhost"])
        manifest = {"plugin_id": "builtin.vlm.vllm_localhost", "permissions": {"network": True}}
        # Should not raise: localhost-only allowlist is valid.
        reg._check_permissions(manifest)

    def test_check_permissions_denies_non_allowlisted_network_plugin(self) -> None:
        reg = self._registry(internet=["builtin.egress.gateway"], localhost=[])
        manifest = {"plugin_id": "builtin.vlm.vllm_localhost", "permissions": {"network": True}}
        with self.assertRaises(PluginError):
            reg._check_permissions(manifest)


if __name__ == "__main__":
    unittest.main()

