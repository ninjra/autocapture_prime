import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from autocapture.promptops.engine import PromptOpsLayer


class PromptOpsTemplateDiffTests(unittest.TestCase):
    def test_template_mapping_diff_records_on_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
            data_dir = Path(tmp) / "data"
            audit_path = Path(tmp) / "audit.db"
            config.setdefault("storage", {})["data_dir"] = str(data_dir)
            config["storage"]["audit_db_path"] = str(audit_path)
            config.setdefault("runtime", {})["run_id"] = "run-test"

            layer = PromptOpsLayer(config)
            layer.prepare_prompt(
                "hello",
                prompt_id="query.test",
                sources=[{"id": "s1", "text": "alpha"}],
                persist=False,
                strategy="none",
            )
            layer.prepare_prompt(
                "hello",
                prompt_id="query.test",
                sources=[{"id": "s1", "text": "alpha"}],
                persist=False,
                strategy="none",
            )
            layer.prepare_prompt(
                "hello",
                prompt_id="query.test",
                sources=[{"id": "s2", "text": "beta"}],
                persist=False,
                strategy="none",
            )

            conn = sqlite3.connect(str(audit_path))
            count = conn.execute(
                "SELECT COUNT(*) FROM template_mapping_diff WHERE mapping_id = ?",
                ("query.test",),
            ).fetchone()[0]
            conn.close()
            self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
