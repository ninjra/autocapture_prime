from __future__ import annotations

import argparse
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autocapture_nx import cli


class CliBatchMetadataPathTests(unittest.TestCase):
    def _args(self) -> argparse.Namespace:
        return argparse.Namespace(safe_mode=True, max_loops=1, sleep_ms=0, require_idle=True)

    def test_cmd_batch_prefers_live_metadata_db_by_default(self) -> None:
        captured: dict[str, str] = {}

        class _Facade:
            def batch_run(self, **_kwargs):  # noqa: ANN001
                captured["AUTOCAPTURE_STORAGE_METADATA_PATH"] = str(os.environ.get("AUTOCAPTURE_STORAGE_METADATA_PATH") or "")
                return {"ok": True}

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            (data_dir / "metadata.live.db").write_text("", encoding="utf-8")
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "AUTOCAPTURE_DATA_DIR": str(data_dir),
                    },
                    clear=True,
                ),
                mock.patch.object(cli, "create_facade", return_value=_Facade()),
                mock.patch.object(cli, "_print_json"),
            ):
                rc = cli.cmd_batch_run(self._args())
        self.assertEqual(rc, 0)
        self.assertEqual(captured.get("AUTOCAPTURE_STORAGE_METADATA_PATH"), str(data_dir / "metadata.live.db"))

    def test_cmd_batch_does_not_override_explicit_metadata_path(self) -> None:
        captured: dict[str, str] = {}

        class _Facade:
            def batch_run(self, **_kwargs):  # noqa: ANN001
                captured["AUTOCAPTURE_STORAGE_METADATA_PATH"] = str(os.environ.get("AUTOCAPTURE_STORAGE_METADATA_PATH") or "")
                return {"ok": True}

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            live = data_dir / "metadata.live.db"
            live.write_text("", encoding="utf-8")
            explicit = data_dir / "metadata.db"
            explicit.write_text("", encoding="utf-8")
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "AUTOCAPTURE_DATA_DIR": str(data_dir),
                        "AUTOCAPTURE_STORAGE_METADATA_PATH": str(explicit),
                    },
                    clear=True,
                ),
                mock.patch.object(cli, "create_facade", return_value=_Facade()),
                mock.patch.object(cli, "_print_json"),
            ):
                rc = cli.cmd_batch_run(self._args())
        self.assertEqual(rc, 0)
        self.assertEqual(captured.get("AUTOCAPTURE_STORAGE_METADATA_PATH"), str(explicit))

    def test_cmd_batch_honors_disable_flag_for_live_metadata_preference(self) -> None:
        captured: dict[str, str] = {}

        class _Facade:
            def batch_run(self, **_kwargs):  # noqa: ANN001
                captured["AUTOCAPTURE_STORAGE_METADATA_PATH"] = str(os.environ.get("AUTOCAPTURE_STORAGE_METADATA_PATH") or "")
                return {"ok": True}

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            (data_dir / "metadata.live.db").write_text("", encoding="utf-8")
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "AUTOCAPTURE_DATA_DIR": str(data_dir),
                        "AUTOCAPTURE_BATCH_METADATA_USE_LIVE_DB": "0",
                    },
                    clear=True,
                ),
                mock.patch.object(cli, "create_facade", return_value=_Facade()),
                mock.patch.object(cli, "_print_json"),
            ):
                rc = cli.cmd_batch_run(self._args())
        self.assertEqual(rc, 0)
        self.assertEqual(captured.get("AUTOCAPTURE_STORAGE_METADATA_PATH"), "")


if __name__ == "__main__":
    unittest.main()
