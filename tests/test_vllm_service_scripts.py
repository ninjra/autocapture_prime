from __future__ import annotations

from pathlib import Path
import unittest


class VllmServiceScriptsTests(unittest.TestCase):
    def test_service_scripts_exist_and_executable(self) -> None:
        root = Path(__file__).resolve().parents[1]
        run_script = root / "services" / "vllm" / "run_vllm.sh"
        health_script = root / "services" / "vllm" / "health.sh"
        self.assertTrue(run_script.exists())
        self.assertTrue(health_script.exists())
        self.assertTrue(run_script.stat().st_mode & 0o111)
        self.assertTrue(health_script.stat().st_mode & 0o111)


if __name__ == "__main__":
    unittest.main()
