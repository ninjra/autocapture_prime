import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.kernel.hashing import sha256_file, sha256_text
from autocapture_nx.kernel.loader import Kernel, KernelBootArgs
from autocapture_nx.kernel.config import ConfigPaths


class KernelEffectiveConfigTests(unittest.TestCase):
    def test_effective_config_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default_path = root / "default.json"
            user_path = root / "user.json"
            schema_path = root / "schema.json"
            backup_dir = root / "backup"

            default = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
            schema = json.loads(Path("contracts/config_schema.json").read_text(encoding="utf-8"))
            default_path.write_text(json.dumps(default, indent=2, sort_keys=True), encoding="utf-8")
            user_path.write_text("{}", encoding="utf-8")
            schema_path.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")

            paths = ConfigPaths(default_path, user_path, schema_path, backup_dir)
            kernel = Kernel(paths, safe_mode=False)
            effective = kernel.load_effective_config()

            self.assertEqual(effective.schema_hash, sha256_file(schema_path))
            self.assertEqual(effective.effective_hash, sha256_text(dumps(effective.data)))

    def test_kernel_boot_args_safe_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default_path = root / "default.json"
            user_path = root / "user.json"
            schema_path = root / "schema.json"
            backup_dir = root / "backup"

            default = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
            schema = json.loads(Path("contracts/config_schema.json").read_text(encoding="utf-8"))
            default_path.write_text(json.dumps(default, indent=2, sort_keys=True), encoding="utf-8")
            schema_path.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")

            args = KernelBootArgs(
                safe_mode=True,
                config_default_path=str(default_path),
                config_user_path=str(user_path),
            )
            kernel = Kernel(args)
            effective = kernel.load_effective_config()
            self.assertTrue(effective.data.get("plugins", {}).get("safe_mode", False))


if __name__ == "__main__":
    unittest.main()
