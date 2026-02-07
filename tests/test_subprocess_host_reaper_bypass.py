import unittest

from autocapture_nx.plugin_system.host import reap_subprocess_hosts


class SubprocessHostReaperBypassTests(unittest.TestCase):
    def test_bypass_interval_gate_returns_not_skipped(self) -> None:
        # We don't rely on any real subprocesses here; this just verifies the
        # interval gate can't cause a "skipped" fast-path when explicitly bypassed.
        now = 123.0
        _first = reap_subprocess_hosts(force=False, bypass_interval_gate=True, now_mono=now)
        _second = reap_subprocess_hosts(force=False, bypass_interval_gate=True, now_mono=now + 0.1)
        self.assertFalse(bool(_second.get("skipped", False)))


if __name__ == "__main__":
    unittest.main()

