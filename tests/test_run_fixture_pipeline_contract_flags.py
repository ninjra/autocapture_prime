import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tools.run_fixture_pipeline as fixture_cli


class _FakeCapture:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


class _FakeMetadata:
    def get(self, record_id: str, default=None):  # noqa: ANN001
        if str(record_id).endswith("evidence.capture.frame/1"):
            return {
                "record_type": "evidence.capture.frame",
                "container": {"type": "blob"},
            }
        return default if default is not None else {}


class _FakeKernel:
    def __init__(self, *_args, **_kwargs) -> None:
        self._system = _FakeSystem()

    def boot(self, **_kwargs):
        return self._system

    def shutdown(self) -> None:
        return None


class _FakeSystem:
    def __init__(self) -> None:
        self.config = {"runtime": {"run_id": "test-run"}}
        self._cap = {
            "capture.source": _FakeCapture(),
            "storage.metadata": _FakeMetadata(),
        }

    def get(self, name: str):
        return self._cap.get(name)


class FixturePipelineContractFlagsTests(unittest.TestCase):
    def test_contract_flags_and_env_produce_isolated_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            frame_dir = tmp_path / "frames"
            frame_dir.mkdir(parents=True, exist_ok=True)
            # Frame content is never decoded in this mocked test path.
            (frame_dir / "frame.png").write_bytes(b"fake")
            manifest_path = tmp_path / "manifest.json"
            manifest_path.write_text("{}", encoding="utf-8")
            out_dir = tmp_path / "out"
            data_root = tmp_path / "data-root"
            ready_file = tmp_path / "ready" / "status.json"
            run_id = "hv_run_001"

            base_user_cfg = {
                "web": {"allow_remote": False, "bind_host": "127.0.0.1"},
                "storage": {"no_deletion_mode": True, "raw_first_local": True},
                "plugins": {"enabled": {"builtin.anchor.basic": True}},
                "runtime": {},
            }
            fake_manifests = [{"plugin_id": "builtin.anchor.basic"}]
            fake_load_report = {"loaded": ["builtin.anchor.basic"], "failed": [], "skipped": [], "errors": []}

            with mock.patch.dict(
                "os.environ",
                {
                    "AP_RUN_ID": run_id,
                    "AP_DATA_ROOT": str(data_root),
                    "AP_NO_NETWORK": "1",
                    "AP_LOG_JSON": "1",
                    "AP_READY_FILE": str(ready_file),
                },
                clear=False,
            ):
                with mock.patch.object(fixture_cli, "load_manifest", return_value={}):
                    with mock.patch.object(fixture_cli, "resolve_screenshots", return_value=[frame_dir / "frame.png"]):
                        with mock.patch.object(fixture_cli, "build_user_config", return_value=json.loads(json.dumps(base_user_cfg))):
                            with mock.patch.object(fixture_cli, "_discover_plugins", return_value=fake_manifests):
                                with mock.patch.object(fixture_cli, "Kernel", _FakeKernel):
                                    with mock.patch.object(fixture_cli, "_wait_for_evidence", return_value=[f"{run_id}/evidence.capture.frame/1"]):
                                        with mock.patch.object(fixture_cli, "collect_plugin_load_report", return_value=fake_load_report):
                                            with mock.patch.object(fixture_cli, "run_idle_processing", return_value={"done": True, "blocked": False}):
                                                with mock.patch.object(
                                                    fixture_cli,
                                                    "build_query_specs",
                                                    return_value=[{"id": "q1"}],
                                                ):
                                                    with mock.patch.object(
                                                        fixture_cli,
                                                        "evaluate_query",
                                                        return_value={"ok": True},
                                                    ):
                                                        with mock.patch.object(fixture_cli, "probe_plugins", return_value=[]):
                                                            with mock.patch.object(
                                                                fixture_cli,
                                                                "collect_plugin_trace",
                                                                return_value={"events": [], "summary": {"plugins": {}}},
                                                            ):
                                                                rc = fixture_cli.main(
                                                                    [
                                                                        "--manifest",
                                                                        str(manifest_path),
                                                                        "--output-dir",
                                                                        str(out_dir),
                                                                        "--input-dir",
                                                                        str(frame_dir),
                                                                    ]
                                                                )
            self.assertEqual(rc, 0)
            run_dir = out_dir / run_id
            report_path = run_dir / "fixture_report.json"
            self.assertTrue(report_path.exists())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report.get("run_id"), run_id)
            self.assertEqual(Path(str(report.get("data_dir"))), data_root / run_id)
            self.assertTrue(bool(report.get("no_network", False)))
            self.assertTrue(bool(report.get("log_json", False)))

            ready = json.loads(ready_file.read_text(encoding="utf-8"))
            self.assertEqual(str(ready.get("status")), "ok")
            self.assertEqual(str(ready.get("run_id")), run_id)

            user_cfg = json.loads((run_dir / "config" / "user.json").read_text(encoding="utf-8"))
            self.assertEqual(user_cfg["privacy"]["egress"]["enabled"], False)
            self.assertEqual(user_cfg["plugins"]["enabled"]["builtin.egress.gateway"], False)


if __name__ == "__main__":
    unittest.main()
