from __future__ import annotations

import unittest
from unittest import mock


class TestLoaderMetaReloadClosesOldPlugins(unittest.TestCase):
    def test_meta_reload_closes_old_plugins(self) -> None:
        # Deterministic regression test for a WSL-crashing leak:
        # Kernel.boot() can load plugins, apply meta plugins, then reload plugins again.
        # The initial plugin instances must be closed before the second load to avoid
        # leaving subprocess plugin hosts alive (runaway RAM/processes).
        from autocapture_nx.kernel.loader import Kernel, KernelBootArgs

        closed: list[str] = []
        call_counter = {"n": 0}

        class DummyInstance:
            def __init__(self, name: str) -> None:
                self._name = name

            def close(self) -> None:
                closed.append(self._name)

        class DummyLoadedPlugin:
            def __init__(self, name: str) -> None:
                self.instance = DummyInstance(name)

        class DummyCaps:
            def __init__(self) -> None:
                # Kernel.boot() checks capabilities via `.all()` for required core writers.
                # This test is about reload/cleanup semantics, so these are inert sentinels.
                self._caps = {
                    "journal.writer": object(),
                    "ledger.writer": object(),
                    "anchor.writer": object(),
                }

            def get(self, _name):  # noqa: ANN001
                return self._caps.get(_name)

            def register(self, *_args, **_kwargs):
                return None

            def all(self):
                return dict(self._caps)

        class DummyRegistry:
            def __init__(self, config, safe_mode=False):  # noqa: ARG002
                self._config = config

            def load_plugins(self):
                idx = call_counter["n"]
                call_counter["n"] = idx + 1
                plugins = [DummyLoadedPlugin(f"p{idx}.a"), DummyLoadedPlugin(f"p{idx}.b")]
                return plugins, DummyCaps()

        kernel = Kernel(KernelBootArgs(safe_mode=False))

        class Effective:
            def __init__(self, data):
                self.data = data

        base_cfg = {"plugins": {"allowlist": [], "enabled": {}}, "storage": {"data_dir": "data"}}

        def _apply_meta_plugins(cfg, _plugins):  # noqa: ANN001
            updated = dict(cfg)
            updated["__meta_updated__"] = True
            return updated

        # Stop early once the reload path has been exercised.
        def _stop(*_args, **_kwargs):  # noqa: ANN001
            raise RuntimeError("stop-after-reload")

        import autocapture_nx.kernel.loader as loader_mod

        with (
            mock.patch.object(kernel, "load_effective_config", side_effect=lambda: Effective(dict(base_cfg))),
            mock.patch.object(
                kernel,
                "_evaluate_crash_loop",
                side_effect=lambda _cfg: type("S", (), {"force_safe_mode": False, "reason": None})(),
            ),
            mock.patch.object(kernel, "_verify_contract_lock", side_effect=lambda: None),
            mock.patch.object(kernel, "_apply_meta_plugins", side_effect=_apply_meta_plugins),
            mock.patch.object(loader_mod, "PluginRegistry", DummyRegistry),
            mock.patch.object(loader_mod, "ensure_run_id", side_effect=lambda _cfg: None),
            mock.patch.object(loader_mod, "apply_runtime_determinism", side_effect=lambda _cfg: None),
            mock.patch.object(loader_mod, "validate_config", side_effect=lambda _schema, _cfg: None),
            mock.patch.object(loader_mod, "global_network_deny", side_effect=lambda: True),
            mock.patch.object(loader_mod, "set_global_network_deny", side_effect=lambda _deny: None),
            mock.patch.object(loader_mod, "EventBuilder", side_effect=_stop),
        ):
            with self.assertRaisesRegex(RuntimeError, "stop-after-reload"):
                kernel.boot(start_conductor=False)

        # First load (p0.*) must be closed before second load is used.
        self.assertIn("p0.a", closed)
        self.assertIn("p0.b", closed)


if __name__ == "__main__":
    unittest.main()
