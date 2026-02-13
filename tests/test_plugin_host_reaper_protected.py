import unittest


class _Host:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _ProtectedInst:
    def __init__(self) -> None:
        self._host = _Host()
        self._in_flight = 0
        self._last_used_mono = 0.0
        self._reap_protected = True
        self.closed_reasons: list[str] = []
        self._config = {"plugins": {"hosting": {"subprocess_max_hosts": 1, "subprocess_idle_ttl_s": 1.0}}}

    def _close_host_for_reap(self, *, reason: str) -> None:
        self.closed_reasons.append(reason)
        if self._host is not None:
            self._host.close()
        self._host = None


class PluginHostReaperProtectedTests(unittest.TestCase):
    def test_reaper_skips_reap_protected_instances(self) -> None:
        from autocapture_nx.plugin_system import host as host_mod

        inst = _ProtectedInst()
        # Make sure the WeakSet keeps a strong reference via this variable.
        with host_mod._SUBPROCESS_INSTANCES_LOCK:  # type: ignore[attr-defined]
            host_mod._SUBPROCESS_INSTANCES.add(inst)  # type: ignore[attr-defined]
        try:
            report = host_mod.reap_subprocess_hosts(force=False, bypass_interval_gate=True, now_mono=100.0)
            self.assertIsNotNone(report)
            self.assertIsNotNone(inst._host)
            self.assertFalse(inst._host.closed)
            self.assertEqual(inst.closed_reasons, [])
        finally:
            with host_mod._SUBPROCESS_INSTANCES_LOCK:  # type: ignore[attr-defined]
                try:
                    host_mod._SUBPROCESS_INSTANCES.discard(inst)  # type: ignore[attr-defined]
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()

