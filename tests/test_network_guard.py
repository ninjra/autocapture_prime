import socket
import unittest

from autocapture_nx.plugin_system.runtime import network_guard
from autocapture_nx.kernel.errors import PermissionError


def _socket_available() -> bool:
    try:
        s = socket.socket()
        s.close()
        return True
    except OSError:
        # Some sandboxed CI environments disallow socket syscalls entirely.
        return False


@unittest.skipUnless(_socket_available(), "socket syscalls are not permitted in this environment")
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
