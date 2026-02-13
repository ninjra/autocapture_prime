from __future__ import annotations

import json
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


def _load_main():
    path = Path("tools/export_run_workflow_tree.py")
    spec = importlib.util.spec_from_file_location("export_run_workflow_tree_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.main


class ExportRunWorkflowTreeTests(unittest.TestCase):
    def test_exports_markdown_from_report_payload(self) -> None:
        payload = {
            "query_arbitrated": {
                "answer": {
                    "display": {
                        "summary": "inboxes: 4",
                        "bullets": ["signals: explicit_inbox_labels=2, mail_client_regions=2, total=4"],
                    }
                },
                "processing": {
                    "attribution": {
                        "providers": [
                            {
                                "provider_id": "builtin.observation.graph",
                                "claim_count": 1,
                                "citation_count": 1,
                                "doc_kinds": ["obs.metric.open_inboxes"],
                            }
                        ],
                        "workflow_tree": {
                            "edges": [
                                {"from": "query", "to": "retrieval.strategy"},
                                {"from": "retrieval.strategy", "to": "builtin.observation.graph"},
                                {"from": "builtin.observation.graph", "to": "answer.builder"},
                            ]
                        },
                    }
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "report.json"
            out = root / "workflow_tree.md"
            report.write_text(json.dumps(payload), encoding="utf-8")
            export_main = _load_main()
            rc = export_main(["--input", str(report), "--out", str(out)])
            self.assertEqual(rc, 0)
            text = out.read_text(encoding="utf-8")
            self.assertIn("Plugin Contributions", text)
            self.assertIn("builtin.observation.graph", text)
            self.assertIn("graph TD", text)


if __name__ == "__main__":
    unittest.main()
