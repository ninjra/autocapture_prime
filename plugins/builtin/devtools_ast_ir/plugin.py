"""AST/IR guided devtools plugin."""

from __future__ import annotations

import ast
import difflib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.canonical_json import dumps
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

    def run(self, scan_root: str = "autocapture_nx") -> dict[str, Any]:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = Path("tools") / "hypervisor" / "runs" / run_id
        os.makedirs(run_dir, exist_ok=True)

        ast_summary = self._scan_python_ast(scan_root)
        design_ir = self._build_design_ir()
        pin_path = Path(self.context.config.get("devtools", {}).get("ast_ir", {}).get("pin_path", "contracts/ir_pins.json"))
        with open(pin_path, "r", encoding="utf-8") as handle:
            pinned = json.load(handle)
        diff = self._diff_ir(design_ir, pinned)
        pinned_ok = diff == ""

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
