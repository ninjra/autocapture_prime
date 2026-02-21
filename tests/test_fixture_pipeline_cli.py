import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class FixturePipelineCliTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import PIL  # noqa: F401
        except Exception:
            self.skipTest("Pillow not available")
        try:
            import sqlcipher3  # noqa: F401
        except Exception:
            self.skipTest("sqlcipher3 not available")

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _write_png(self, path: Path, text: str) -> None:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (480, 240), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        draw.text((10, 10), text, fill=(0, 0, 0), font=font)
        img.save(path, format="PNG")

    def test_fixture_cli_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            frame_dir = tmp_path / "frames"
            frame_dir.mkdir(parents=True, exist_ok=True)
            png_path = frame_dir / "fixture.png"
            # Avoid digit/letter OCR confusables (e.g. 1 vs I) to keep the
            # fixture pipeline deterministic across OCR backends.
            self._write_png(png_path, "FIXTUREABC")

            manifest = {
                "fixture_id": "test-fixture",
                "version": 1,
                "inputs": {"screenshots": [{"id": "s1", "path": str(png_path)}]},
                "queries": {
                    "mode": "explicit",
                    "explicit": [{"query": "FIXTUREABC"}],
                    "require_citations": True,
                    "require_state": "ok",
                },
            }
            manifest_path = tmp_path / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            output_dir = tmp_path / "out"
            cmd = [
                sys.executable,
                "tools/run_fixture_pipeline.py",
                "--manifest",
                str(manifest_path),
                "--output-dir",
                str(output_dir),
                "--input-dir",
                str(frame_dir),
            ]
            result = subprocess.run(
                cmd,
                cwd=self._repo_root(),
                env=os.environ.copy(),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            reports = list(output_dir.rglob("fixture_report.json"))
            self.assertTrue(reports)
            report = json.loads(reports[0].read_text(encoding="utf-8"))
            queries = report.get("queries", {})
            self.assertEqual(queries.get("failures"), 0)
            config_dir = Path(report.get("config_dir") or "")
            user_path = config_dir / "user.json"
            self.assertTrue(user_path.exists())
            self.assertNotIn("{data_dir}", user_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
