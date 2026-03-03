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
                captured["AUTOCAPTURE_STORAGE_METADATA_PATH_STRICT"] = str(
                    os.environ.get("AUTOCAPTURE_STORAGE_METADATA_PATH_STRICT") or ""
                )
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
        self.assertEqual(captured.get("AUTOCAPTURE_STORAGE_METADATA_PATH_STRICT"), "1")

    def test_cmd_batch_does_not_override_explicit_metadata_path(self) -> None:
        captured: dict[str, str] = {}

        class _Facade:
            def batch_run(self, **_kwargs):  # noqa: ANN001
                captured["AUTOCAPTURE_STORAGE_METADATA_PATH"] = str(os.environ.get("AUTOCAPTURE_STORAGE_METADATA_PATH") or "")
                captured["AUTOCAPTURE_STORAGE_METADATA_PATH_STRICT"] = str(
                    os.environ.get("AUTOCAPTURE_STORAGE_METADATA_PATH_STRICT") or ""
                )
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
        self.assertEqual(captured.get("AUTOCAPTURE_STORAGE_METADATA_PATH_STRICT"), "1")

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

    def test_cmd_batch_prefers_primary_when_both_dbs_exist_under_freshest_policy(self) -> None:
        captured: dict[str, str] = {}

        class _Facade:
            def batch_run(self, **_kwargs):  # noqa: ANN001
                captured["AUTOCAPTURE_STORAGE_METADATA_PATH"] = str(os.environ.get("AUTOCAPTURE_STORAGE_METADATA_PATH") or "")
                captured["AUTOCAPTURE_STORAGE_METADATA_PATH_STRICT"] = str(
                    os.environ.get("AUTOCAPTURE_STORAGE_METADATA_PATH_STRICT") or ""
                )
                captured["AUTOCAPTURE_BATCH_METADATA_SELECTION_REASON"] = str(
                    os.environ.get("AUTOCAPTURE_BATCH_METADATA_SELECTION_REASON") or ""
                )
                return {"ok": True}

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            live = data_dir / "metadata.live.db"
            primary = data_dir / "metadata.db"
            live.write_text("", encoding="utf-8")
            primary.write_text("", encoding="utf-8")
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
        self.assertEqual(captured.get("AUTOCAPTURE_STORAGE_METADATA_PATH"), str(primary))
        self.assertEqual(captured.get("AUTOCAPTURE_STORAGE_METADATA_PATH_STRICT"), "1")
        self.assertEqual(captured.get("AUTOCAPTURE_BATCH_METADATA_SELECTION_REASON"), "freshest_primary_preferred")

    def test_cmd_batch_prefers_live_when_live_is_materially_newer(self) -> None:
        captured: dict[str, str] = {}

        class _Facade:
            def batch_run(self, **_kwargs):  # noqa: ANN001
                captured["AUTOCAPTURE_STORAGE_METADATA_PATH"] = str(os.environ.get("AUTOCAPTURE_STORAGE_METADATA_PATH") or "")
                captured["AUTOCAPTURE_STORAGE_METADATA_PATH_STRICT"] = str(
                    os.environ.get("AUTOCAPTURE_STORAGE_METADATA_PATH_STRICT") or ""
                )
                captured["AUTOCAPTURE_BATCH_METADATA_SELECTION_REASON"] = str(
                    os.environ.get("AUTOCAPTURE_BATCH_METADATA_SELECTION_REASON") or ""
                )
                return {"ok": True}

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            live = data_dir / "metadata.live.db"
            primary = data_dir / "metadata.db"
            primary.write_text("", encoding="utf-8")
            live.write_text("", encoding="utf-8")
            # Force live to appear much newer than primary.
            old_ts = 1_700_000_000
            new_ts = old_ts + 120
            os.utime(primary, (old_ts, old_ts))
            os.utime(live, (new_ts, new_ts))
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
        self.assertEqual(captured.get("AUTOCAPTURE_STORAGE_METADATA_PATH"), str(live))
        self.assertEqual(captured.get("AUTOCAPTURE_STORAGE_METADATA_PATH_STRICT"), "1")
        self.assertEqual(captured.get("AUTOCAPTURE_BATCH_METADATA_SELECTION_REASON"), "freshest_live_newer")

    def test_cmd_batch_prefers_readable_live_when_primary_is_unreadable(self) -> None:
        captured: dict[str, str] = {}

        class _Facade:
            def batch_run(self, **_kwargs):  # noqa: ANN001
                captured["AUTOCAPTURE_STORAGE_METADATA_PATH"] = str(os.environ.get("AUTOCAPTURE_STORAGE_METADATA_PATH") or "")
                captured["AUTOCAPTURE_BATCH_METADATA_SELECTION_REASON"] = str(
                    os.environ.get("AUTOCAPTURE_BATCH_METADATA_SELECTION_REASON") or ""
                )
                return {"ok": True}

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            live = data_dir / "metadata.live.db"
            primary = data_dir / "metadata.db"
            primary.write_text("", encoding="utf-8")
            live.write_text("", encoding="utf-8")

            def _probe(path: Path) -> tuple[bool, str]:
                if path == primary:
                    return False, "OperationalError:disk I/O error"
                return True, "ok"

            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "AUTOCAPTURE_DATA_DIR": str(data_dir),
                    },
                    clear=True,
                ),
                mock.patch.object(cli, "_probe_sqlite_readable", side_effect=_probe),
                mock.patch.object(cli, "create_facade", return_value=_Facade()),
                mock.patch.object(cli, "_print_json"),
            ):
                rc = cli.cmd_batch_run(self._args())
        self.assertEqual(rc, 0)
        self.assertEqual(captured.get("AUTOCAPTURE_STORAGE_METADATA_PATH"), str(live))
        self.assertEqual(
            captured.get("AUTOCAPTURE_BATCH_METADATA_SELECTION_REASON"),
            "freshest_primary_unreadable_live_readable",
        )

    def test_cmd_batch_prefers_live_when_primary_has_no_frame_ts(self) -> None:
        captured: dict[str, str] = {}

        class _Facade:
            def batch_run(self, **_kwargs):  # noqa: ANN001
                captured["AUTOCAPTURE_STORAGE_METADATA_PATH"] = str(os.environ.get("AUTOCAPTURE_STORAGE_METADATA_PATH") or "")
                captured["AUTOCAPTURE_BATCH_METADATA_SELECTION_REASON"] = str(
                    os.environ.get("AUTOCAPTURE_BATCH_METADATA_SELECTION_REASON") or ""
                )
                return {"ok": True}

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            live = data_dir / "metadata.live.db"
            primary = data_dir / "metadata.db"
            primary.write_text("", encoding="utf-8")
            live.write_text("", encoding="utf-8")

            def _probe_frame(path: Path, _record_type: str) -> tuple[int | None, str]:
                if path == primary:
                    return None, "none"
                return 1_772_159_200_000_000_000, "ok"

            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "AUTOCAPTURE_DATA_DIR": str(data_dir),
                    },
                    clear=True,
                ),
                mock.patch.object(cli, "_probe_latest_record_ts_ns", side_effect=_probe_frame),
                mock.patch.object(cli, "create_facade", return_value=_Facade()),
                mock.patch.object(cli, "_print_json"),
            ):
                rc = cli.cmd_batch_run(self._args())
        self.assertEqual(rc, 0)
        self.assertEqual(captured.get("AUTOCAPTURE_STORAGE_METADATA_PATH"), str(live))
        self.assertEqual(captured.get("AUTOCAPTURE_BATCH_METADATA_SELECTION_REASON"), "freshest_live_frame_only")


if __name__ == "__main__":
    unittest.main()
