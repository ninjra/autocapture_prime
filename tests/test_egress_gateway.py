import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths, SchemaLiteValidator, load_config
from autocapture_nx.plugin_system.registry import PluginRegistry


def _localhost_bind_available() -> bool:
    import socket

    try:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.close()
        return True
    except OSError:
        # Some sandboxed CI environments disallow socket syscalls entirely.
        return False


@unittest.skipUnless(_localhost_bind_available(), "localhost socket bind is not permitted in this environment")
class EgressGatewayTests(unittest.TestCase):
    def test_reasoning_packet_schema(self):
        payloads: list[dict] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - http.server uses do_* naming
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length).decode("utf-8")
                payloads.append(json.loads(raw) if raw else {})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))

            def log_message(self, _format, *_args):  # pragma: no cover - silence server logs
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                paths = ConfigPaths(
                    default_path=Path("config") / "default.json",
                    user_path=Path(tmp) / "user.json",
                    schema_path=Path("contracts") / "config_schema.json",
                    backup_dir=Path(tmp) / "backup",
                )
                base_url = f"http://127.0.0.1:{server.server_port}"
                safe_tmp = tmp.replace("\\", "/")
                user_override = {
                    "storage": {
                        "data_dir": safe_tmp,
                        "crypto": {
                            "keyring_path": f"{safe_tmp}/keyring.json",
                            "root_key_path": f"{safe_tmp}/root.key",
                        },
                    },
                    "gateway": {
                        "openai_base_url": base_url,
                        "egress_path": "/v1/egress",
                    },
                    "plugins": {
                        "permissions": {"network_allowed_plugin_ids": ["builtin.egress.gateway"]},
                    },
                    "privacy": {
                        "cloud": {"enabled": True},
                        "egress": {"default_sanitize": True, "approval_required": False},
                    },
                }
                with open(paths.user_path, "w", encoding="utf-8") as handle:
                    json.dump(user_override, handle)
                config = load_config(paths, safe_mode=False)
                registry = PluginRegistry(config, safe_mode=False)
                _plugins, caps = registry.load_plugins()
                gateway = caps.get("egress.gateway")
                payload = {
                    "query": "Email john@example.com about the report",
                    "facts": [{"type": "event", "ts_utc": "2025-01-01T00:00:00Z", "fields": {"owner": "John Doe"}}],
                    "time_window": {"start": "2025-01-01T00:00:00Z", "end": "2025-01-02T00:00:00Z"},
                }
                response = gateway.send(payload)
                packet = response["payload"]
                schema_path = Path("contracts") / "reasoning_packet.schema.json"
                with open(schema_path, "r", encoding="utf-8") as handle:
                    schema = json.load(handle)
                SchemaLiteValidator().validate(schema, packet)
                self.assertNotIn("john@example.com", packet["query_sanitized"])
                self.assertEqual(response.get("status"), "ok")
                self.assertTrue(payloads)
                self.assertIn("query_sanitized", payloads[0])
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
