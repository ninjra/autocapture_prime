from __future__ import annotations

import argparse
import os
import unittest
from unittest import mock

from autocapture_nx import cli


class CliQueryMetadataOnlyTests(unittest.TestCase):
    def test_cmd_query_sets_metadata_only_defaults(self) -> None:
        captured: dict[str, str] = {}

        class _Facade:
            def query(self, text: str):  # noqa: ANN001
                captured["text"] = text
                captured["AUTOCAPTURE_QUERY_METADATA_ONLY"] = str(os.environ.get("AUTOCAPTURE_QUERY_METADATA_ONLY") or "")
                captured["AUTOCAPTURE_ADV_HARD_VLM_MODE"] = str(os.environ.get("AUTOCAPTURE_ADV_HARD_VLM_MODE") or "")
                captured["AUTOCAPTURE_AUDIT_PLUGIN_METADATA"] = str(os.environ.get("AUTOCAPTURE_AUDIT_PLUGIN_METADATA") or "")
                captured["AUTOCAPTURE_RETRIEVAL_LATEST_SCAN_LIMIT"] = str(
                    os.environ.get("AUTOCAPTURE_RETRIEVAL_LATEST_SCAN_LIMIT") or ""
                )
                return {"ok": True}

        args = argparse.Namespace(safe_mode=True, text="hello")
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(cli, "create_facade", return_value=_Facade()),
            mock.patch.object(cli, "_print_json"),
        ):
            rc = cli.cmd_query(args)
        self.assertEqual(rc, 0)
        self.assertEqual(captured.get("text"), "hello")
        self.assertEqual(captured.get("AUTOCAPTURE_QUERY_METADATA_ONLY"), "1")
        self.assertEqual(captured.get("AUTOCAPTURE_ADV_HARD_VLM_MODE"), "off")
        self.assertEqual(captured.get("AUTOCAPTURE_AUDIT_PLUGIN_METADATA"), "0")
        self.assertEqual(captured.get("AUTOCAPTURE_RETRIEVAL_LATEST_SCAN_LIMIT"), "250")
