"""AST/IR guided devtools plugin."""

from __future__ import annotations

import ast
import difflib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.kernel.ids import ensure_run_id
from autocapture_nx.kernel.paths import resolve_repo_path
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


@dataclass
class CodeASTSummary:
    files: int
    functions: int
    classes: int


class ASTIRTool(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"devtools.ast_ir": self}

    def _scan_python_ast(self, root: str) -> CodeASTSummary:
        path = Path(root)
        files = 0
        functions = 0
        classes = 0
        for file_path in path.rglob("*.py"):
            files += 1
            with open(file_path, "r", encoding="utf-8") as handle:
                node = ast.parse(handle.read())
            for item in ast.walk(node):
                if isinstance(item, ast.FunctionDef):
                    functions += 1
                elif isinstance(item, ast.ClassDef):
                    classes += 1
        return CodeASTSummary(files=files, functions=functions, classes=classes)

    def _build_design_ir(self) -> dict[str, Any]:
        cfg = self.context.config
        plugins = []
        for pid, enabled in cfg.get("plugins", {}).get("enabled", {}).items():
            plugins.append({"id": pid, "enabled": bool(enabled)})
        ir = {
            "schema_version": 1,
            "config_schema_version": cfg.get("schema_version"),
            "plugins": sorted(plugins, key=lambda p: p["id"]),
            "capabilities": sorted(cfg.get("kernel", {}).get("required_capabilities", [])),
            "permissions": {
                "network_allowed": sorted(
                    cfg.get("plugins", {})
                    .get("permissions", {})
                    .get("network_allowed_plugin_ids", [])
                )
            },
            "config_keys": sorted(cfg.keys()),
        }
        return ir

    def _diff_ir(self, current: dict[str, Any], pinned: dict[str, Any]) -> str:
        current_text = dumps(current).splitlines()
        pinned_text = dumps(pinned).splitlines()
        diff = difflib.unified_diff(pinned_text, current_text, fromfile="pinned", tofile="current")
        return "\n".join(diff)

    def _compat_pinned(self, current: dict[str, Any], pinned: dict[str, Any]) -> tuple[bool, str]:
        notes: list[str] = []
        ok = True

        if int(current.get("schema_version", 0) or 0) != int(pinned.get("schema_version", 0) or 0):
            ok = False
            notes.append("schema_version mismatch")
        if int(current.get("config_schema_version", 0) or 0) != int(pinned.get("config_schema_version", 0) or 0):
            ok = False
            notes.append("config_schema_version mismatch")

        current_caps = set(current.get("capabilities", []))
        pinned_caps = set(pinned.get("capabilities", []))
        missing_caps = sorted(pinned_caps - current_caps)
        if missing_caps:
            ok = False
            notes.append("missing capabilities: " + ", ".join(missing_caps))

        current_keys = set(current.get("config_keys", []))
        pinned_keys = set(pinned.get("config_keys", []))
        missing_keys = sorted(pinned_keys - current_keys)
        if missing_keys:
            ok = False
            notes.append("missing config_keys: " + ", ".join(missing_keys))

        current_net = set((current.get("permissions", {}) or {}).get("network_allowed", []))
        pinned_net = set((pinned.get("permissions", {}) or {}).get("network_allowed", []))
        missing_net = sorted(pinned_net - current_net)
        if missing_net:
            ok = False
            notes.append("missing permissions.network_allowed: " + ", ".join(missing_net))

        current_plugins = {str(p.get("id", "")): bool(p.get("enabled", False)) for p in current.get("plugins", [])}
        for plugin in pinned.get("plugins", []):
            pid = str(plugin.get("id", ""))
            expected = bool(plugin.get("enabled", False))
            actual = current_plugins.get(pid)
            if actual is None:
                ok = False
                notes.append(f"missing plugin: {pid}")
                continue
            # Treat "expected disabled, currently enabled" as forward-compatible.
            # Still fail when a plugin expected enabled is now disabled.
            if expected and not actual:
                ok = False
                notes.append(f"plugin enabled mismatch: {pid} expected={expected} actual={actual}")

        return ok, "\n".join(notes)

    def run(self, scan_root: str = "autocapture_nx") -> dict[str, Any]:
        run_id = ensure_run_id(self.context.config)
        data_dir = self.context.config.get("storage", {}).get("data_dir")
        if not data_dir:
            data_dir = os.getenv("AUTOCAPTURE_DATA_DIR", "data")
        data_dir_path = Path(str(data_dir))
        if not data_dir_path.is_absolute():
            data_dir_path = resolve_repo_path(data_dir_path)
        run_dir = data_dir_path / "runs" / run_id / "devtools_ast_ir"
        os.makedirs(run_dir, exist_ok=True)

        ast_summary = self._scan_python_ast(scan_root)
        design_ir = self._build_design_ir()
        raw_pin = self.context.config.get("devtools", {}).get("ast_ir", {}).get("pin_path", "contracts/ir_pins.json")
        pin_path = Path(raw_pin)
        if not pin_path.is_absolute():
            pin_path = resolve_repo_path(pin_path)
        with open(pin_path, "r", encoding="utf-8") as handle:
            pinned = json.load(handle)
        pinned_ok, compat_notes = self._compat_pinned(design_ir, pinned)
        diff = "" if pinned_ok else compat_notes

        result = {
            "run_id": run_id,
            "ast": ast_summary.__dict__,
            "ir": design_ir,
            "pinned_ok": pinned_ok,
            "diff": diff,
        }
        with open(run_dir / "ast_ir.json", "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
        return result


def create_plugin(plugin_id: str, context: PluginContext) -> ASTIRTool:
    return ASTIRTool(plugin_id, context)
