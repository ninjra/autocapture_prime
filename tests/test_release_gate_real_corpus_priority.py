from __future__ import annotations

import importlib.util
import pathlib
import sys
from unittest import mock


def _load_module():
    path = pathlib.Path("tools/release_gate.py")
    spec = importlib.util.spec_from_file_location("release_gate_tool_priority", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_manifest_places_real_corpus_gate_before_q40_when_both_enabled() -> None:
    mod = _load_module()
    with mock.patch.dict(mod.os.environ, {"REAL_CORPUS_STRICT_REPORT": "/tmp/real.json", "Q40_STRICT_REPORT": "/tmp/q40.json"}):
        steps = mod._default_manifest(sys.executable)
    ids = [step.id for step in steps]
    assert "run_real_corpus_readiness" in ids
    assert "gate_real_corpus_strict" in ids
    assert "gate_q40_strict" in ids
    assert ids.index("run_real_corpus_readiness") < ids.index("gate_real_corpus_strict")
    assert ids.index("gate_real_corpus_strict") < ids.index("gate_q40_strict")


def test_release_stops_on_real_corpus_fail_before_q40(tmp_path: pathlib.Path) -> None:
    mod = _load_module()

    class _FakeStep:
        def __init__(self, sid: str):
            self.id = sid
            self.cmd = ["echo", sid]
            self.artifact = None

    fake_steps = [_FakeStep("gate_real_corpus_strict"), _FakeStep("gate_q40_strict")]
    with (
        mock.patch.object(mod, "_default_manifest", return_value=fake_steps),
        mock.patch.object(
            mod,
            "_run_step",
            side_effect=[
                {"id": "gate_real_corpus_strict", "ok": False, "returncode": 1, "issues": ["failed_nonzero"]},
                {"id": "gate_q40_strict", "ok": True, "returncode": 0, "issues": []},
            ],
        ) as run_mock,
    ):
        payload = mod.run_release_gate(root=tmp_path, strict_status=True)
    assert payload["ok"] is False
    assert payload["failed_step"] == "gate_real_corpus_strict"
    assert payload["steps_executed"] == 1
    assert run_mock.call_count == 1


def test_manifest_passes_explicit_real_corpus_artifact_paths() -> None:
    mod = _load_module()
    with mock.patch.dict(
        mod.os.environ,
        {
            "REAL_CORPUS_ADVANCED_JSON": "/tmp/adv_real.json",
            "REAL_CORPUS_GENERIC_JSON": "/tmp/gen_real.json",
        },
        clear=False,
    ):
        steps = mod._default_manifest(sys.executable)
    readiness = [step for step in steps if step.id == "run_real_corpus_readiness"]
    assert len(readiness) == 1
    cmd = readiness[0].cmd
    assert "--advanced-json" in cmd
    assert "/tmp/adv_real.json" in cmd
    assert "--generic-json" in cmd
    assert "/tmp/gen_real.json" in cmd


def test_manifest_adds_real_corpus_determinism_when_enabled() -> None:
    mod = _load_module()
    with mock.patch.dict(
        mod.os.environ,
        {
            "REAL_CORPUS_DETERMINISM_ENABLED": "1",
            "REAL_CORPUS_DETERMINISM_RUNS": "5",
        },
        clear=False,
    ):
        steps = mod._default_manifest(sys.executable)
    ids = [step.id for step in steps]
    assert "gate_real_corpus_determinism" in ids
