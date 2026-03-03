from __future__ import annotations

from contextlib import contextmanager
import unittest
from unittest import mock


class _System:
    def __init__(self) -> None:
        self.config = {
            "storage": {
                "data_dir": "/tmp/autocapture",
                "metadata_path": "/tmp/autocapture/metadata.live.db",
            }
        }

    def has(self, _capability: str) -> bool:
        return True

    def get(self, _capability: str):  # noqa: ANN001
        return object()


class _KernelMgr:
    def __init__(self) -> None:
        self._system = _System()

    @contextmanager
    def session(self):
        yield self._system

    def last_error(self):
        return None


class FacadeQueryHardFailStaleTests(unittest.TestCase):
    def test_guard_uses_derived_overlay_stage2_for_primary_selection(self) -> None:
        from autocapture_nx.ux.facade import _evaluate_query_hard_fail_guard

        config = {
            "storage": {
                "data_dir": "/tmp/autocapture",
                "metadata_path": "/tmp/autocapture/metadata.db",
            }
        }

        def _probe(path):  # noqa: ANN001
            p = str(path)
            if p.endswith("metadata.db"):
                return True, "ok"
            if p.endswith("metadata.live.db"):
                return True, "ok"
            if p.endswith("stage1_derived.db"):
                return True, "ok"
            return False, "missing"

        def _max_ts(path, record_type):  # noqa: ANN001
            p = str(path)
            if p.endswith("metadata.db") and record_type == "evidence.capture.frame":
                return "2026-02-28T03:59:03+00:00", "ok"
            if p.endswith("metadata.db") and record_type == "derived.ingest.stage2.complete":
                return None, "ok"
            if p.endswith("stage1_derived.db") and record_type == "derived.ingest.stage2.complete":
                return "2026-02-28T03:59:02+00:00", "ok"
            return None, "missing"

        with (
            mock.patch.dict(
                "os.environ",
                {
                    "AUTOCAPTURE_QUERY_FRESHNESS_FAIL_HOURS": "24",
                    "AUTOCAPTURE_QUERY_STAGE2_PROGRESS_MAX_GAP_HOURS": "2",
                },
                clear=False,
            ),
            mock.patch("autocapture_nx.ux.facade._sqlite_probe_readonly", side_effect=_probe),
            mock.patch("autocapture_nx.ux.facade._sqlite_max_ts", side_effect=_max_ts),
        ):
            out = _evaluate_query_hard_fail_guard(config)

        self.assertTrue(bool(out.get("ok", False)))
        self.assertEqual(str(out.get("selected_stage2_fallback") or ""), "derived_overlay")
        self.assertEqual(str(out.get("latest_stage2_ts_utc") or ""), "2026-02-28T03:59:02+00:00")

    def test_guard_falls_back_to_live_when_primary_unreadable(self) -> None:
        from autocapture_nx.ux.facade import _evaluate_query_hard_fail_guard

        config = {
            "storage": {
                "data_dir": "/tmp/autocapture",
                "metadata_path": "/tmp/autocapture/metadata.live.db",
            }
        }

        def _probe(path):  # noqa: ANN001
            p = str(path)
            if p.endswith("metadata.db"):
                return False, "DatabaseError:database disk image is malformed"
            if p.endswith("metadata.live.db"):
                return True, "ok"
            return False, "missing"

        def _max_ts(path, record_type):  # noqa: ANN001
            p = str(path)
            if p.endswith("metadata.live.db") and record_type == "evidence.capture.frame":
                return "2026-02-27T17:00:00+00:00", "ok"
            if p.endswith("metadata.live.db") and record_type == "derived.ingest.stage2.complete":
                return "2026-02-27T16:59:30+00:00", "ok"
            return None, "missing"

        with (
            mock.patch.dict(
                "os.environ",
                {
                    "AUTOCAPTURE_QUERY_ALLOW_LIVE_FALLBACK_ON_PRIMARY_UNREADABLE": "1",
                    "AUTOCAPTURE_QUERY_FRESHNESS_FAIL_HOURS": "24",
                },
                clear=False,
            ),
            mock.patch("autocapture_nx.ux.facade._sqlite_probe_readonly", side_effect=_probe),
            mock.patch("autocapture_nx.ux.facade._sqlite_max_ts", side_effect=_max_ts),
        ):
            out = _evaluate_query_hard_fail_guard(config)

        self.assertTrue(bool(out.get("ok", False)))
        self.assertEqual(str(out.get("frame_source_path") or ""), "/tmp/autocapture/metadata.live.db")
        self.assertEqual(str(out.get("effective_selected_metadata_path") or ""), "/tmp/autocapture/metadata.live.db")
        self.assertTrue(bool(out.get("primary_degraded", False)))

    def test_facade_query_hard_fails_when_freshness_guard_fails(self) -> None:
        from autocapture_nx.ux.facade import UXFacade

        facade = UXFacade(persistent=True, auto_start_capture=False)
        facade._kernel_mgr = _KernelMgr()  # noqa: SLF001
        with (
            mock.patch.dict(
                "os.environ",
                {
                    "AUTOCAPTURE_QUERY_METADATA_ONLY": "1",
                    "AUTOCAPTURE_QUERY_HARD_FAIL_STALE": "1",
                },
                clear=False,
            ),
            mock.patch(
                "autocapture_nx.ux.facade._evaluate_query_hard_fail_guard",
                return_value={
                    "ok": False,
                    "error": "freshness_lag_exceeded",
                    "detail": "stage2_lag_hours=100.0>max=15.0",
                    "freshness_lag_hours": 100.0,
                },
            ),
            mock.patch("autocapture_nx.ux.facade.run_query") as run_query_mock,
        ):
            out = facade.query("what happened today")

        self.assertFalse(bool(out.get("ok")))
        self.assertEqual(str(out.get("error") or ""), "freshness_lag_exceeded")
        processing = out.get("processing", {}) if isinstance(out.get("processing", {}), dict) else {}
        extraction = processing.get("extraction", {}) if isinstance(processing.get("extraction", {}), dict) else {}
        self.assertEqual(str(extraction.get("blocked_reason") or ""), "freshness_lag_exceeded")
        trace = processing.get("query_trace", {}) if isinstance(processing.get("query_trace", {}), dict) else {}
        self.assertEqual(str(trace.get("error") or ""), "freshness_lag_exceeded")
        self.assertEqual(run_query_mock.call_count, 0)

    def test_facade_query_runs_when_freshness_guard_passes(self) -> None:
        from autocapture_nx.ux.facade import UXFacade

        facade = UXFacade(persistent=True, auto_start_capture=False)
        facade._kernel_mgr = _KernelMgr()  # noqa: SLF001
        with (
            mock.patch.dict(
                "os.environ",
                {
                    "AUTOCAPTURE_QUERY_METADATA_ONLY": "1",
                    "AUTOCAPTURE_QUERY_HARD_FAIL_STALE": "1",
                },
                clear=False,
            ),
            mock.patch(
                "autocapture_nx.ux.facade._evaluate_query_hard_fail_guard",
                return_value={"ok": True},
            ),
            mock.patch(
                "autocapture_nx.ux.facade.run_query",
                return_value={"ok": True, "answer": {"state": "supported"}},
            ) as run_query_mock,
        ):
            out = facade.query("what happened today")

        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(run_query_mock.call_count, 1)
