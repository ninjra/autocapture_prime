"""Command line interface for Autocapture NX."""

from __future__ import annotations

import argparse
import json
import sys

from autocapture_nx.kernel.config import (
    ConfigPaths,
    load_config,
    reset_user_config,
    restore_user_config,
)
from autocapture_nx.kernel.errors import AutocaptureError
from autocapture_nx.kernel.loader import Kernel, default_config_paths
from autocapture_nx.kernel.key_rotation import rotate_keys
from autocapture_nx.kernel.query import run_query
from autocapture_nx.plugin_system.registry import PluginRegistry


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def cmd_doctor(args: argparse.Namespace) -> int:
    kernel = Kernel(default_config_paths(), safe_mode=args.safe_mode)
    kernel.boot()
    checks = kernel.doctor()
    ok = all(check.ok for check in checks)
    for check in checks:
        status = "OK" if check.ok else "FAIL"
        print(f"{status} {check.name}: {check.detail}")
    return 0 if ok else 2


def cmd_config_show(_args: argparse.Namespace) -> int:
    paths = default_config_paths()
    config = load_config(paths, safe_mode=False)
    _print_json(config)
    return 0


def cmd_config_reset(_args: argparse.Namespace) -> int:
    paths = default_config_paths()
    reset_user_config(paths)
    print("User config reset to defaults")
    return 0


def cmd_config_restore(_args: argparse.Namespace) -> int:
    paths = default_config_paths()
    restore_user_config(paths)
    print("User config restored from backup")
    return 0


def cmd_plugins_list(args: argparse.Namespace) -> int:
    paths = default_config_paths()
    config = load_config(paths, safe_mode=args.safe_mode)
    registry = PluginRegistry(config, safe_mode=args.safe_mode)
    manifests = registry.discover_manifests()
    allowlist = set(config.get("plugins", {}).get("allowlist", []))
    enabled = config.get("plugins", {}).get("enabled", {})

    rows = []
    for manifest_path in manifests:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        pid = manifest["plugin_id"]
        rows.append(
            {
                "plugin_id": pid,
                "allowlisted": pid in allowlist,
                "enabled": enabled.get(pid, manifest.get("enabled", True)),
                "path": str(manifest_path.parent),
            }
        )
    _print_json({"plugins": sorted(rows, key=lambda r: r["plugin_id"])})
    return 0


def cmd_plugins_approve(_args: argparse.Namespace) -> int:
    from tools.hypervisor.scripts.update_plugin_locks import update_plugin_locks

    update_plugin_locks()
    print("Plugin lockfile updated")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    kernel = Kernel(default_config_paths(), safe_mode=args.safe_mode)
    system = kernel.boot()
    capture = system.get("capture.source")
    audio = system.get("capture.audio")
    input_tracker = system.get("tracking.input")
    window_meta = system.get("window.metadata")
    capture.start()
    audio.start()
    input_tracker.start()
    window_meta.start()
    print("Capture running. Press Ctrl+C to stop.")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        capture.stop()
        audio.stop()
        input_tracker.stop()
        window_meta.stop()
        return 0


def cmd_devtools_diffusion(args: argparse.Namespace) -> int:
    kernel = Kernel(default_config_paths(), safe_mode=args.safe_mode)
    system = kernel.boot()
    harness = system.get("devtools.diffusion")
    result = harness.run(axis=args.axis, k_variants=args.k, dry_run=args.dry_run)
    _print_json(result)
    return 0


def cmd_devtools_ast_ir(args: argparse.Namespace) -> int:
    kernel = Kernel(default_config_paths(), safe_mode=args.safe_mode)
    system = kernel.boot()
    tool = system.get("devtools.ast_ir")
    result = tool.run(scan_root=args.scan_root)
    _print_json(result)
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    kernel = Kernel(default_config_paths(), safe_mode=args.safe_mode)
    system = kernel.boot()
    result = run_query(system, args.text)
    _print_json(result)
    return 0


def cmd_keys_rotate(args: argparse.Namespace) -> int:
    kernel = Kernel(default_config_paths(), safe_mode=args.safe_mode)
    system = kernel.boot()
    result = rotate_keys(system)
    _print_json(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autocapture")
    parser.add_argument("--safe-mode", action="store_true", help="Boot in safe mode")

    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor")
    doctor.set_defaults(func=cmd_doctor)

    cfg = sub.add_parser("config")
    cfg_sub = cfg.add_subparsers(dest="config_cmd", required=True)
    cfg_show = cfg_sub.add_parser("show")
    cfg_show.set_defaults(func=cmd_config_show)
    cfg_reset = cfg_sub.add_parser("reset")
    cfg_reset.set_defaults(func=cmd_config_reset)
    cfg_restore = cfg_sub.add_parser("restore")
    cfg_restore.set_defaults(func=cmd_config_restore)

    plugins = sub.add_parser("plugins")
    plugins_sub = plugins.add_subparsers(dest="plugins_cmd", required=True)
    plugins_list = plugins_sub.add_parser("list")
    plugins_list.set_defaults(func=cmd_plugins_list)
    plugins_approve = plugins_sub.add_parser("approve")
    plugins_approve.set_defaults(func=cmd_plugins_approve)

    run_cmd = sub.add_parser("run")
    run_cmd.set_defaults(func=cmd_run)

    query_cmd = sub.add_parser("query")
    query_cmd.add_argument("text")
    query_cmd.set_defaults(func=cmd_query)

    devtools = sub.add_parser("devtools")
    devtools_sub = devtools.add_subparsers(dest="devtools_cmd", required=True)
    diffusion = devtools_sub.add_parser("diffusion")
    diffusion.add_argument("--axis", required=True)
    diffusion.add_argument("-k", type=int, default=1)
    diffusion.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=None)
    diffusion.set_defaults(func=cmd_devtools_diffusion)
    ast_ir = devtools_sub.add_parser("ast-ir")
    ast_ir.add_argument("--scan-root", default="autocapture_nx")
    ast_ir.set_defaults(func=cmd_devtools_ast_ir)

    keys = sub.add_parser("keys")
    keys_sub = keys.add_subparsers(dest="keys_cmd", required=True)
    rotate = keys_sub.add_parser("rotate")
    rotate.set_defaults(func=cmd_keys_rotate)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        exit_code = args.func(args)
    except AutocaptureError as exc:
        print(f"ERROR: {exc}")
        exit_code = 1
    sys.exit(exit_code)
