import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


class PackageSafePathsTests(unittest.TestCase):
    def test_loads_resources_from_any_cwd(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = textwrap.dedent(
            """
            import json
            from autocapture_nx.kernel.loader import default_config_paths
            from autocapture_nx.kernel.config import load_config
            from autocapture_nx.plugin_system.registry import PluginRegistry

            paths = default_config_paths()
            config = load_config(paths, safe_mode=True)
            registry = PluginRegistry(config, safe_mode=True)
            manifests = registry.discover_manifests()
            if not manifests:
                raise SystemExit("no_manifests_found")
            registry.load_lockfile()
            with open(manifests[0].path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            registry._validate_manifest(manifest)
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(root)
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        if result.returncode != 0:
            output = (result.stdout + "\n" + result.stderr).strip()
            self.fail(f"Resource resolution failed outside repo CWD: {output}")


if __name__ == "__main__":
    unittest.main()
