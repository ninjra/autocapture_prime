import json
import tempfile
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import ConfigPaths, SchemaLiteValidator, load_config
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.egress_gateway.plugin import EgressGateway
from plugins.builtin.egress_sanitizer.plugin import EgressSanitizer


class EgressGatewayTests(unittest.TestCase):
    def test_reasoning_packet_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = ConfigPaths(
                default_path=Path("config") / "default.json",
                user_path=Path(tmp) / "user.json",
                schema_path=Path("contracts") / "config_schema.json",
                backup_dir=Path(tmp) / "backup",
            )
            safe_tmp = tmp.replace("\\", "/")
            user_override = {
                "storage": {
                    "data_dir": safe_tmp,
                    "crypto": {
                        "keyring_path": f"{safe_tmp}/keyring.json",
                        "root_key_path": f"{safe_tmp}/root.key",
                    },
                },
                "privacy": {
                    "cloud": {"enabled": True}
                },
            }
            with open(paths.user_path, "w", encoding="utf-8") as handle:
                json.dump(user_override, handle)
            config = load_config(paths, safe_mode=False)
            sanitizer = EgressSanitizer("sanitizer", PluginContext(config=config, get_capability=lambda _k: (_ for _ in ()).throw(Exception()), logger=lambda _m: None))

            def get_capability(name: str):
                if name == "privacy.egress_sanitizer":
                    return sanitizer
                raise KeyError(name)

            gateway = EgressGateway("gateway", PluginContext(config=config, get_capability=get_capability, logger=lambda _m: None))
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


if __name__ == "__main__":
    unittest.main()
