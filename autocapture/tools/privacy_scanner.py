"""Privacy scanner gate for P3."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.egress_sanitizer.plugin import EgressSanitizer


def _load_defaults() -> dict:
    return json.loads(Path("config/default.json").read_text(encoding="utf-8"))


def _build_sanitizer(tmp_dir: str) -> EgressSanitizer:
    root_key = b"privacy_gate_key_v1".ljust(32, b"_")
    root_path = Path(tmp_dir) / "root.key"
    root_path.write_bytes(root_key)
    config = _load_defaults()
    config.setdefault("storage", {}).setdefault("crypto", {})["root_key_path"] = str(root_path)
    config["storage"]["crypto"]["keyring_path"] = str(Path(tmp_dir) / "keyring.json")
    ctx = PluginContext(config=config, get_capability=lambda _k: (_ for _ in ()).throw(Exception()), logger=lambda _m: None)
    return EgressSanitizer("privacy.scanner", ctx)


def run() -> dict:
    defaults = _load_defaults()
    privacy = defaults.get("privacy", {})
    cloud = privacy.get("cloud", {})
    egress = privacy.get("egress", {})
    issues: list[str] = []

    if cloud.get("enabled", True):
        issues.append("cloud_enabled_by_default")
    if cloud.get("allow_images", True):
        issues.append("cloud_images_enabled")
    if not egress.get("default_sanitize", False):
        issues.append("default_sanitize_disabled")
    if egress.get("allow_raw_egress", True):
        issues.append("allow_raw_egress_true")
    if not egress.get("reasoning_packet_only", False):
        issues.append("reasoning_packet_only_false")

    with tempfile.TemporaryDirectory() as tmp:
        sanitizer = _build_sanitizer(tmp)
        text = "Contact Jane Doe at jane@example.com or 555-123-4567."
        sanitized = sanitizer.sanitize_text(text)
        leak_ok = sanitizer.leak_check({"text": sanitized["text"], "_tokens": sanitized["tokens"]})
        if not leak_ok:
            issues.append("sanitizer_leak_check_failed")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
    }
