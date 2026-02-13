"""Update plugin manifests with static `provides` capability keys.

Why:
- Subprocess plugin hosting on WSL can OOM if we eagerly spawn a host_runner per
  plugin just to discover capabilities at boot time.
- If manifests declare `provides`, the registry can seed capability keys without
  starting the subprocess until first actual use (lazy start).

This tool parses plugin source via `ast` (no importing), extracts dict-literal
keys returned by `capabilities()` methods, and writes them to each `plugin.json`.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class PluginProvideUpdate:
    plugin_id: str
    manifest_path: Path
    provides: list[str]
    changed: bool
    reason: str | None = None


class _CapabilitiesExtractor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.keys: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name != "capabilities":
            return
        for child in node.body:
            if isinstance(child, ast.Return):
                self._extract_return(child.value)

    def _extract_return(self, value: ast.AST | None) -> None:
        if value is None:
            return
        if isinstance(value, ast.Dict):
            for key in value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    text = key.value.strip()
                    if text:
                        self.keys.add(text)
        # Some plugins return a local variable; keep this simple and safe.


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _extract_provides_from_source(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    extractor = _CapabilitiesExtractor()
    extractor.visit(tree)
    return sorted(extractor.keys)


def update_manifest(manifest_path: Path) -> PluginProvideUpdate | None:
    manifest = _read_json(manifest_path)
    plugin_id = str(manifest.get("plugin_id", "")).strip()
    if not plugin_id:
        return None
    entrypoints = manifest.get("entrypoints", [])
    if not isinstance(entrypoints, list) or not entrypoints:
        return PluginProvideUpdate(plugin_id, manifest_path, [], False, reason="no_entrypoints")
    # Prefer the primary entrypoint file for capability inference.
    entry = entrypoints[0] if isinstance(entrypoints[0], dict) else {}
    rel_path = str(entry.get("path", "")).strip()
    if not rel_path:
        return PluginProvideUpdate(plugin_id, manifest_path, [], False, reason="missing_entrypoint_path")
    source_path = manifest_path.parent / rel_path
    if not source_path.exists():
        return PluginProvideUpdate(plugin_id, manifest_path, [], False, reason=f"missing_source:{rel_path}")

    provides = _extract_provides_from_source(source_path)
    if not provides:
        return PluginProvideUpdate(plugin_id, manifest_path, [], False, reason="no_static_capabilities")

    existing = manifest.get("provides", [])
    existing_list = [str(x).strip() for x in existing] if isinstance(existing, list) else []
    existing_list = sorted({x for x in existing_list if x})

    changed = existing_list != provides
    if changed:
        manifest["provides"] = provides
        _write_json(manifest_path, manifest)
    return PluginProvideUpdate(plugin_id, manifest_path, provides, changed, reason=None)


def main() -> int:
    root = REPO_ROOT / "plugins"
    updates: list[PluginProvideUpdate] = []
    for manifest_path in sorted(root.rglob("plugin.json")):
        update = update_manifest(manifest_path)
        if update is None:
            continue
        updates.append(update)

    changed = [u for u in updates if u.changed]
    skipped = [u for u in updates if (not u.changed and u.reason)]
    print(f"OK: scanned={len(updates)} changed={len(changed)} skipped={len(skipped)}")
    for u in skipped[:60]:
        print(f"skip: {u.plugin_id}: {u.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

