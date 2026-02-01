import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.audit import append_audit_event


class AuditLogTests(unittest.TestCase):
    def test_append_only_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            append_audit_event(action="test.one", actor="unit", outcome="ok", details={"a": 1}, log_path=path)
            append_audit_event(action="test.two", actor="unit", outcome="ok", details={"b": 2}, log_path=path)
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            first = json.loads(lines[0])
            second = json.loads(lines[1])
            self.assertEqual(first["action"], "test.one")
            self.assertEqual(second["action"], "test.two")


if __name__ == "__main__":
    unittest.main()
