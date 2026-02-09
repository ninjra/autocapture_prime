from __future__ import annotations

from autocapture_nx.kernel.consent import accept_capture_consent, consent_path, load_capture_consent
from autocapture_nx.ux.facade import UXFacade
from autocapture_nx.kernel.loader import default_config_paths


def test_consent_file_roundtrip(tmp_path) -> None:
    consent = load_capture_consent(data_dir=tmp_path)
    assert consent.accepted is False
    assert consent.accepted_ts_utc is None

    accepted = accept_capture_consent(data_dir=tmp_path)
    assert accepted.accepted is True
    assert accepted.accepted_ts_utc

    path = consent_path(data_dir=tmp_path)
    assert path.exists()

    consent2 = load_capture_consent(data_dir=tmp_path)
    assert consent2.accepted is True
    assert consent2.accepted_ts_utc == accepted.accepted_ts_utc


def test_facade_blocks_capture_when_consent_missing(tmp_path, monkeypatch) -> None:
    # Ensure config resolves, but consent is checked before kernel boot.
    monkeypatch.setenv("AUTOCAPTURE_DATA_DIR", str(tmp_path))
    # Keep default config dir; only data_dir is overridden.
    facade = UXFacade(paths=default_config_paths(), persistent=False, safe_mode=False)
    res = facade.run_start()
    assert res["ok"] is False
    assert res["error"] == "consent_required"
    facade.shutdown()


def test_facade_ledgers_capture_start_stop_when_builder_present(tmp_path, monkeypatch) -> None:
    # Accept consent so run_start proceeds past gating, but do not boot a real kernel.
    accept_capture_consent(data_dir=tmp_path)
    monkeypatch.setenv("AUTOCAPTURE_DATA_DIR", str(tmp_path))

    calls = []

    class _Builder:
        def ledger_entry(self, stage, inputs, outputs, payload=None, **_kw):
            calls.append((stage, list(inputs), list(outputs), dict(payload or {})))
            return "hash"

    class _System:
        def get(self, name):
            if name == "event.builder":
                return _Builder()
            return None

    # Build facade without starting the real kernel.
    facade = UXFacade(paths=default_config_paths(), persistent=False, safe_mode=False)

    def _fake_start_components():
        facade._run_active = True  # type: ignore[attr-defined]

    def _fake_stop_components():
        facade._run_active = False  # type: ignore[attr-defined]

    from contextlib import contextmanager

    @contextmanager
    def _fake_session():
        yield _System()

    facade._start_components = _fake_start_components  # type: ignore[method-assign]
    facade._stop_components = _fake_stop_components  # type: ignore[method-assign]
    facade._kernel_mgr.session = _fake_session  # type: ignore[method-assign]

    assert facade.run_start()["ok"] is True
    # run_stop requires capture_controls to be enabled; force it on for this test.
    facade._config.setdefault("runtime", {}).setdefault("capture_controls", {})["enabled"] = True  # type: ignore[index]
    assert facade.run_stop()["ok"] is True
    stages = [c[0] for c in calls]
    assert "operator.capture.start" in stages
    assert "operator.capture.stop" in stages
    facade.shutdown()
