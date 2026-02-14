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

    def test_exports_per_row_bundle_from_advanced_artifact(self) -> None:
        payload = {
            "rows": [
                {
                    "id": "Q1",
                    "question": "Enumerate windows",
                    "answer_state": "ok",
                    "winner": "classic",
                    "summary": "windows extracted",
                    "stage_ms": {"total": 123.4},
                    "providers": [
                        {
                            "provider_id": "builtin.observation.graph",
                            "claim_count": 3,
                            "citation_count": 3,
                            "contribution_bp": 10000,
                            "estimated_latency_ms": 45.0,
                        }
                    ],
                },
                {
                    "id": "Q2",
                    "question": "Which window is focused",
                    "answer_state": "ok",
                    "winner": "classic",
                    "summary": "focused window extracted",
                    "stage_ms": {"total": 98.2},
                    "providers": [],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "advanced.json"
            out_dir = root / "trees"
            artifact.write_text(json.dumps(payload), encoding="utf-8")
            export_main = _load_main()
            rc = export_main(["--input", str(artifact), "--out", str(out_dir)])
            self.assertEqual(rc, 0)
            index = (out_dir / "index.md").read_text(encoding="utf-8")
            q1 = (out_dir / "workflow_tree_Q1.md").read_text(encoding="utf-8")
            q2 = (out_dir / "workflow_tree_Q2.md").read_text(encoding="utf-8")
            self.assertIn("[Q1](workflow_tree_Q1.md)", index)
            self.assertIn("builtin.observation.graph", q1)
            self.assertIn("display.formatter", q2)


if __name__ == "__main__":
    unittest.main()
