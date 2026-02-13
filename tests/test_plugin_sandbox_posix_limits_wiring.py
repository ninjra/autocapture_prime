import os
import unittest


class _DummyProc:
    def __init__(self) -> None:
        self.pid = 12345
        self.stdin = object()
        self.stdout = object()


class TestSandboxSpawnPosixWiring(unittest.TestCase):
    def test_posix_spawn_sets_session_and_preexec(self) -> None:
        # This test is about wiring, not enforcement. Enforcement is best-effort
        # and platform-specific, but we still want to ensure we *attempt* to set
        # rlimits and parent-death behavior on non-Windows.
        if os.name == "nt":
            self.skipTest("posix wiring test")
        from autocapture_nx.plugin_system import sandbox as sb

        captured = {}

        def fake_popen(*args, **kwargs):
            captured["kwargs"] = dict(kwargs)
            return _DummyProc()

        orig_popen = sb.subprocess.Popen
        try:
            sb.subprocess.Popen = fake_popen  # type: ignore[assignment]
            proc, report = sb.spawn_plugin_process(
                ["python", "-c", "print('x')"],
                env=None,
                limits={"max_memory_mb": 32, "cpu_time_ms": 1000, "max_processes": 1},
                ipc_max_bytes=1024,
            )
        finally:
            sb.subprocess.Popen = orig_popen  # type: ignore[assignment]

        self.assertIsInstance(proc, _DummyProc)
        popen_kwargs = captured.get("kwargs", {})
        self.assertTrue(popen_kwargs.get("start_new_session"), "expected start_new_session on posix")
        self.assertTrue(callable(popen_kwargs.get("preexec_fn")), "expected preexec_fn on posix")
        self.assertIn("posix_start_new_session", report.notes)
        self.assertIn("posix_pdeathsig_sigterm", report.notes)
        self.assertTrue(any(note.startswith("posix_rlimit_as_mb=") for note in report.notes))
        self.assertTrue(any(note.startswith("posix_rlimit_cpu_ms=") for note in report.notes))
        self.assertTrue(any(note.startswith("posix_max_processes_unenforced=") for note in report.notes))


if __name__ == "__main__":
    unittest.main()
