from autocapture.runtime.conductor import RuntimeConductor


class _DummySystem:
    def __init__(self, config):
        self.config = config

    def has(self, _name: str) -> bool:
        return False

    def get(self, _name: str):
        raise KeyError(_name)


def test_fixture_override_emits_audit(monkeypatch):
    events = []

    def _audit_stub(*, action, actor, outcome, details=None, log_path=None):
        events.append(
            {
                "action": action,
                "actor": actor,
                "outcome": outcome,
                "details": details or {},
            }
        )

    monkeypatch.setattr("autocapture.runtime.conductor.append_audit_event", _audit_stub)

    cfg = {
        "runtime": {
            "run_id": "run_test",
            "mode_enforcement": {"fixture_override": True, "fixture_override_reason": "test"},
        }
    }
    system = _DummySystem(cfg)
    conductor = RuntimeConductor(system)
    _ = conductor._signals()
    assert any(ev["action"] == "runtime.fixture_override" for ev in events)
