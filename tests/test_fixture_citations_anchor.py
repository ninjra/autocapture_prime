import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class FixtureCitationAnchorTests(unittest.TestCase):
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

    def test_fixture_missing_anchor_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            frame_dir = tmp_path / "frames"
            frame_dir.mkdir(parents=True, exist_ok=True)
            png_path = frame_dir / "fixture.png"
            self._write_png(png_path, "ANCHORFAIL")

            manifest = {
                "fixture_id": "test-anchor",
                "version": 1,
                "inputs": {"screenshots": [{"id": "s1", "path": str(png_path)}]},
                "queries": {
                    "mode": "explicit",
                    "explicit": [{"query": "ANCHORFAIL"}],
                    "require_citations": True,
                    "require_state": "ok",
                },
            }
            manifest_path = tmp_path / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            template_src = self._repo_root() / "tools/fixture_config_template.json"
            template = json.loads(template_src.read_text(encoding="utf-8"))
            template.setdefault("storage", {}).setdefault("anchor", {})["every_entries"] = 1000
            template_path = tmp_path / "fixture_template.json"
            template_path.write_text(json.dumps(template, indent=2), encoding="utf-8")

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
                "--config-template",
                str(template_path),
            ]
            result = subprocess.run(
                cmd,
                cwd=self._repo_root(),
                env=os.environ.copy(),
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)

            reports = list(output_dir.rglob("fixture_report.json"))
            self.assertTrue(reports)
            report = json.loads(reports[0].read_text(encoding="utf-8"))
            queries = report.get("queries", {})
            self.assertGreater(int(queries.get("failures", 0)), 0)


if __name__ == "__main__":
    unittest.main()
