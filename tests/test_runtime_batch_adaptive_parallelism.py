import unittest
from unittest import mock

from autocapture_nx.runtime.batch import (
    _apply_adaptive_idle_parallelism,
    _apply_retention_sla_pressure,
    _build_landscape_manifest,
    _estimate_sla_snapshot,
    _metadata_db_guard,
    run_processing_batch,
)


class RuntimeBatchAdaptiveParallelismTests(unittest.TestCase):
    def _base_config(self) -> dict:
        return {
            "runtime": {
                "budgets": {
                    "cpu_max_utilization": 0.5,
                    "ram_max_utilization": 0.5,
                }
            },
            "processing": {
                "idle": {
                    "max_concurrency_cpu": 2,
                    "batch_size": 6,
                    "max_items_per_run": 40,
                    "adaptive_parallelism": {
                        "enabled": True,
                        "cpu_min": 1,
                        "cpu_max": 4,
                        "cpu_step_up": 1,
                        "cpu_step_down": 1,
                        "batch_per_worker": 3,
                        "items_per_worker": 20,
                        "batch_min": 3,
                        "batch_max": 18,
                        "items_min": 20,
                        "items_max": 120,
                        "low_watermark": 0.65,
                        "high_watermark": 0.9,
                    },
                }
            },
        }

    def test_scale_up_when_resource_pressure_is_low(self) -> None:
        config = self._base_config()
        snapshot = _apply_adaptive_idle_parallelism(
            config,
            signals={"cpu_utilization": 0.10, "ram_utilization": 0.10},
        )
        self.assertIsInstance(snapshot, dict)
        self.assertEqual(config["processing"]["idle"]["max_concurrency_cpu"], 3)
        self.assertEqual(config["processing"]["idle"]["batch_size"], 9)
        self.assertEqual(config["processing"]["idle"]["max_items_per_run"], 60)
        self.assertEqual(snapshot["action"], "scale_up")

    def test_scale_down_when_resource_pressure_is_high(self) -> None:
        config = self._base_config()
        config["processing"]["idle"]["max_concurrency_cpu"] = 4
        config["processing"]["idle"]["batch_size"] = 12
        config["processing"]["idle"]["max_items_per_run"] = 80
        snapshot = _apply_adaptive_idle_parallelism(
            config,
            signals={"cpu_utilization": 0.49, "ram_utilization": 0.20},
        )
        self.assertIsInstance(snapshot, dict)
        self.assertEqual(config["processing"]["idle"]["max_concurrency_cpu"], 3)
        self.assertEqual(config["processing"]["idle"]["batch_size"], 9)
        self.assertEqual(config["processing"]["idle"]["max_items_per_run"], 60)
        self.assertEqual(snapshot["action"], "scale_down")

    def test_hold_when_resource_pressure_is_midrange(self) -> None:
        config = self._base_config()
        snapshot = _apply_adaptive_idle_parallelism(
            config,
            signals={"cpu_utilization": 0.35, "ram_utilization": 0.30},
        )
        self.assertIsInstance(snapshot, dict)
        self.assertEqual(config["processing"]["idle"]["max_concurrency_cpu"], 2)
        self.assertEqual(config["processing"]["idle"]["batch_size"], 6)
        self.assertEqual(config["processing"]["idle"]["max_items_per_run"], 40)
        self.assertEqual(snapshot["action"], "hold")

    def test_scale_up_when_queue_backlog_high_and_latency_healthy(self) -> None:
        config = self._base_config()
        snapshot = _apply_adaptive_idle_parallelism(
            config,
            signals={"cpu_utilization": 0.35, "ram_utilization": 0.30},
            recent_steps=[
                {
                    "consumed_ms": 500,
                    "idle_stats": {"pending_records": 1200, "records_completed": 30},
                    "sla": {"pending_records": 1200},
                }
            ],
        )
        self.assertIsInstance(snapshot, dict)
        self.assertEqual(snapshot["action"], "scale_up")
        self.assertEqual(str(snapshot.get("reason") or ""), "queue_high")
        self.assertEqual(config["processing"]["idle"]["max_concurrency_cpu"], 3)

    def test_scale_down_when_latency_p95_exceeds_hard_cap(self) -> None:
        config = self._base_config()
        config["processing"]["idle"]["max_concurrency_cpu"] = 4
        config["processing"]["idle"]["batch_size"] = 12
        config["processing"]["idle"]["max_items_per_run"] = 80
        snapshot = _apply_adaptive_idle_parallelism(
            config,
            signals={"cpu_utilization": 0.35, "ram_utilization": 0.30},
            recent_steps=[
                {"consumed_ms": 4500, "idle_stats": {"pending_records": 200}},
                {"consumed_ms": 4200, "idle_stats": {"pending_records": 180}},
                {"consumed_ms": 4600, "idle_stats": {"pending_records": 160}},
            ],
        )
        self.assertIsInstance(snapshot, dict)
        self.assertEqual(snapshot["action"], "scale_down")
        self.assertEqual(str(snapshot.get("reason") or ""), "latency_p95_hard_cap")
        self.assertEqual(config["processing"]["idle"]["max_concurrency_cpu"], 2)

    def test_disabled_tuning_is_noop(self) -> None:
        config = self._base_config()
        config["processing"]["idle"]["adaptive_parallelism"]["enabled"] = False
        snapshot = _apply_adaptive_idle_parallelism(
            config,
            signals={"cpu_utilization": 0.10, "ram_utilization": 0.10},
        )
        self.assertIsNone(snapshot)
        self.assertEqual(config["processing"]["idle"]["max_concurrency_cpu"], 2)
        self.assertEqual(config["processing"]["idle"]["batch_size"], 6)
        self.assertEqual(config["processing"]["idle"]["max_items_per_run"], 40)

    def test_sla_snapshot_flags_retention_risk_when_no_throughput(self) -> None:
        config = self._base_config()
        config["storage"] = {"retention": {"evidence": "6d"}}
        config["processing"]["idle"]["sla_control"] = {
            "enabled": True,
            "retention_horizon_hours": 144,
            "lag_warn_ratio": 0.8,
            "cpu_step_up_on_risk": 1,
        }
        snapshot = _estimate_sla_snapshot(
            config,
            steps=[
                {"consumed_ms": 5000, "idle_stats": {"pending_records": 200, "records_completed": 0}},
            ],
        )
        self.assertTrue(snapshot["retention_risk"])
        self.assertEqual(snapshot["pending_records"], 200)
        self.assertEqual(snapshot["throughput_records_per_s"], 0.0)
        self.assertGreater(int(snapshot.get("loop_latency_p95_ms") or 0), 0)

    def test_sla_pressure_scales_up_when_risky(self) -> None:
        config = self._base_config()
        config["processing"]["idle"]["sla_control"] = {
            "enabled": True,
            "retention_horizon_hours": 144,
            "lag_warn_ratio": 0.8,
            "cpu_step_up_on_risk": 1,
        }
        config["processing"]["idle"]["adaptive_parallelism"]["cpu_max"] = 4
        result = _apply_retention_sla_pressure(
            config,
            previous_sla={"retention_risk": True},
        )
        self.assertIsInstance(result, dict)
        self.assertEqual(config["processing"]["idle"]["max_concurrency_cpu"], 3)
        self.assertEqual(config["processing"]["idle"]["batch_size"], 9)
        self.assertEqual(config["processing"]["idle"]["max_items_per_run"], 60)

    def test_landscape_manifest_canonicalizes_float_fields(self) -> None:
        config = self._base_config()
        manifest = _build_landscape_manifest(
            config,
            stats=[
                {
                    "loop": 0,
                    "consumed_ms": 1000,
                    "idle_stats": {
                        "records_completed": 1,
                        "pending_records": 2,
                    },
                    "sla": {"throughput_records_per_s": 1.25, "projected_lag_hours": float("inf")},
                }
            ],
            sla={"throughput_records_per_s": 1.25, "projected_lag_hours": float("inf")},
            done=False,
            blocked_reason="active_user",
            loops=1,
        )
        self.assertIsInstance(manifest.get("payload_hash"), str)
        sla = manifest.get("sla", {}) if isinstance(manifest.get("sla"), dict) else {}
        self.assertEqual(sla.get("throughput_records_per_s"), "1.250000")
        self.assertEqual(sla.get("projected_lag_hours"), "inf")

    def test_metadata_db_guard_fail_closed_blocks_on_churn(self) -> None:
        config = self._base_config()
        config["processing"]["idle"]["metadata_db_guard"] = {
            "enabled": True,
            "fail_closed": True,
            "sample_count": 3,
            "poll_interval_ms": 50,
        }
        with mock.patch(
            "autocapture_nx.runtime.batch.metadata_db_stability_snapshot",
            return_value={"ok": False, "exists": True, "stable": False, "reason": "metadata_db_churn_detected"},
        ):
            guard = _metadata_db_guard(config)
        self.assertIsInstance(guard, dict)
        self.assertFalse(bool(guard.get("ok", True)))
        self.assertTrue(bool(guard.get("fail_closed", False)))
        self.assertEqual(str(guard.get("reason")), "metadata_db_churn_detected")

    def test_metadata_db_guard_warn_only_when_fail_closed_disabled(self) -> None:
        config = self._base_config()
        config["processing"]["idle"]["metadata_db_guard"] = {
            "enabled": True,
            "fail_closed": False,
            "sample_count": 3,
            "poll_interval_ms": 50,
        }
        with mock.patch(
            "autocapture_nx.runtime.batch.metadata_db_stability_snapshot",
            return_value={"ok": False, "exists": True, "stable": False, "reason": "metadata_db_churn_detected"},
        ):
            guard = _metadata_db_guard(config)
        self.assertIsInstance(guard, dict)
        self.assertFalse(bool(guard.get("ok", True)))
        self.assertFalse(bool(guard.get("fail_closed", True)))

    def test_run_processing_batch_fail_closed_guard_blocks_without_processing(self) -> None:
        class _Governor:
            def update_config(self, _cfg):  # noqa: ANN001
                return None

        class _Conductor:
            def __init__(self) -> None:
                self._governor = _Governor()

            def _signals(self):  # noqa: ANN001
                return {}

        class _System:
            def __init__(self, base: dict[str, object]) -> None:
                self.config = base

            def get(self, _name):  # noqa: ANN001
                return None

        system = _System(self._base_config())
        with (
            mock.patch("autocapture_nx.runtime.batch.create_conductor", return_value=_Conductor()),
            mock.patch("autocapture_nx.runtime.batch.IdleProcessor"),
            mock.patch(
                "autocapture_nx.runtime.batch._metadata_db_guard",
                return_value={
                    "enabled": True,
                    "ok": False,
                    "fail_closed": True,
                    "reason": "metadata_db_churn_detected",
                    "snapshot": {"stable": False},
                },
            ),
        ):
            out = run_processing_batch(system, max_loops=5, sleep_ms=1, require_idle=True)
        self.assertFalse(bool(out.get("ok", True)))
        self.assertEqual(str(out.get("blocked_reason") or ""), "metadata_db_churn_detected")
        self.assertEqual(int(out.get("loops") or 0), 0)
        guard = out.get("metadata_db_guard", {}) if isinstance(out.get("metadata_db_guard", {}), dict) else {}
        self.assertFalse(bool(guard.get("ok", True)))
        self.assertIn("metadata_db_unstable", [str(x) for x in (out.get("slo_alerts") or [])])


if __name__ == "__main__":
    unittest.main()
