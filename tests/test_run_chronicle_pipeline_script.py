from __future__ import annotations

from pathlib import Path
import unittest


class RunChroniclePipelineScriptTests(unittest.TestCase):
    def test_script_exists_and_executable(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "tools" / "run_chronicle_pipeline.sh"
        self.assertTrue(script.exists())
        self.assertTrue(script.stat().st_mode & 0o111)


if __name__ == "__main__":
    unittest.main()
