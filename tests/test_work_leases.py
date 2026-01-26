import time
import unittest

from autocapture.runtime.leases import LeaseManager


class WorkLeaseTests(unittest.TestCase):
    def test_acquire_release(self) -> None:
        manager = LeaseManager()
        self.assertTrue(manager.acquire("job1", "owner", ttl_s=1))
        self.assertFalse(manager.acquire("job1", "other", ttl_s=1))
        self.assertTrue(manager.is_active("job1"))
        self.assertTrue(manager.release("job1", "owner"))
        self.assertFalse(manager.is_active("job1"))

    def test_expiration(self) -> None:
        manager = LeaseManager()
        self.assertTrue(manager.acquire("job2", "owner", ttl_s=1))
        time.sleep(1.1)
        self.assertFalse(manager.is_active("job2"))

    def test_cancel(self) -> None:
        manager = LeaseManager()
        manager.acquire("job3", "owner", ttl_s=5)
        self.assertTrue(manager.cancel("job3"))
        self.assertFalse(manager.is_active("job3"))


if __name__ == "__main__":
    unittest.main()
