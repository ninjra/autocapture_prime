import os
import socket
import tempfile
import unittest

from autocapture_nx.kernel.errors import PermissionError
from autocapture_nx.kernel.loader import Kernel, default_config_paths


class KernelNetworkDenyTests(unittest.TestCase):
    def test_kernel_blocks_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_config = os.environ.get("AUTOCAPTURE_CONFIG_DIR")
            original_data = os.environ.get("AUTOCAPTURE_DATA_DIR")
            os.environ["AUTOCAPTURE_CONFIG_DIR"] = tmp
            os.environ["AUTOCAPTURE_DATA_DIR"] = tmp
            try:
                kernel = Kernel(default_config_paths(), safe_mode=False)
                system = kernel.boot(start_conductor=False)
                _ = system
                try:
                    with self.assertRaises(PermissionError):
                        sock = socket.socket()
                        try:
                            sock.connect(("203.0.113.1", 80))
                        finally:
                            sock.close()
                finally:
                    kernel.shutdown()
                sock = socket.socket()
                sock.close()
            finally:
                if original_config is None:
                    os.environ.pop("AUTOCAPTURE_CONFIG_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_CONFIG_DIR"] = original_config
                if original_data is None:
                    os.environ.pop("AUTOCAPTURE_DATA_DIR", None)
                else:
                    os.environ["AUTOCAPTURE_DATA_DIR"] = original_data


if __name__ == "__main__":
    unittest.main()
