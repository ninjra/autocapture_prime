import unittest

from autocapture_nx.windows.win_sandbox import (
    build_job_limits,
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
    JOB_OBJECT_LIMIT_JOB_MEMORY,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    JOB_OBJECT_LIMIT_PROCESS_MEMORY,
)


class WinSandboxLimitTests(unittest.TestCase):
    def test_build_job_limits(self) -> None:
        info = build_job_limits({"max_processes": 1, "max_memory_mb": 64, "cpu_time_ms": 5000})
        flags = int(info.BasicLimitInformation.LimitFlags)
        self.assertTrue(flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        self.assertTrue(flags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS)
        self.assertTrue(flags & JOB_OBJECT_LIMIT_PROCESS_MEMORY)
        self.assertTrue(flags & JOB_OBJECT_LIMIT_JOB_MEMORY)
        self.assertEqual(int(info.BasicLimitInformation.ActiveProcessLimit), 1)
        self.assertEqual(int(info.ProcessMemoryLimit), 64 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
