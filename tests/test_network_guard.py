import socket
import unittest

from autocapture_nx.plugin_system.runtime import network_guard
from autocapture_nx.kernel.errors import PermissionError


class NetworkGuardTests(unittest.TestCase):
    def test_network_blocked(self):
        with self.assertRaises(PermissionError):
            with network_guard(enabled=False):
                socket.socket()

    def test_network_allowed(self):
        with network_guard(enabled=True):
            s = socket.socket()
            s.close()


if __name__ == "__main__":
    unittest.main()
