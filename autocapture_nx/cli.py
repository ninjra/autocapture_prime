"""Command line interface for Autocapture NX."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from autocapture_nx.kernel.config import (
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
    kernel.shutdown()
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
    for manifest in manifests:
        pid = manifest.plugin_id
        rows.append(
            {
                "plugin_id": pid,
                "allowlisted": pid in allowlist,
                "enabled": enabled.get(pid, manifest.enabled),
                "path": str(manifest.path.parent),
            }
        )
    from autocapture.plugins.manager import PluginManager

    mx_manager = PluginManager(config, safe_mode=args.safe_mode)
    mx_plugins = mx_manager.list_plugins()
    plugins = {item["plugin_id"]: item for item in rows}
    for item in mx_plugins:
        if item["plugin_id"] not in plugins:
            plugins[item["plugin_id"]] = item
    payload = {
        "plugins": sorted(plugins.values(), key=lambda r: r["plugin_id"]),
        "extensions": mx_manager.list_extensions(),
    }
    _print_json(payload)
    return 0


def cmd_plugins_approve(_args: argparse.Namespace) -> int:
    from tools.hypervisor.scripts.update_plugin_locks import update_plugin_locks

    update_plugin_locks()
    print("Plugin lockfile updated")
    return 0


def cmd_plugins_verify_defaults(_args: argparse.Namespace) -> int:
    from autocapture.codex.validators import _validator_plugins_have_ids, _validator_plugins_have_kinds
    from autocapture.codex.spec import ValidatorSpec

    ids = ValidatorSpec(
        type="plugins_have_ids",
        config={
            "required_plugin_ids": [
                "mx.core.capture_win",
                "mx.core.storage_sqlite",
                "mx.core.ocr_local",
                "mx.core.llm_local",
                "mx.core.llm_openai_compat",
                "mx.core.embed_local",
                "mx.core.vector_local",
                "mx.core.retrieval_tiers",
                "mx.core.compression_and_verify",
                "mx.core.egress_sanitizer",
                "mx.core.export_import",
                "mx.core.web_ui",
                "mx.prompts.default",
                "mx.training.default",
                "mx.research.default",
            ]
        },
    )
    kinds = ValidatorSpec(
        type="plugins_have_kinds",
        config={
            "required_kinds": [
                "capture.source",
                "capture.encoder",
                "activity.signal",
                "storage.blob_backend",
                "storage.media_backend",
                "spans_v2.backend",
                "ocr.engine",
                "llm.provider",
                "decode.backend",
                "embedder.text",
                "vector.backend",
                "retrieval.strategy",
                "reranker.provider",
                "compressor",
                "verifier",
                "egress.sanitizer",
                "export.bundle",
                "import.bundle",
                "ui.panel",
                "ui.overlay",
                "prompt.bundle",
                "training.pipeline",
                "research.source",
                "research.watchlist",
            ]
        },
    )
    ids_result = _validator_plugins_have_ids(ids)
    kinds_result = _validator_plugins_have_kinds(kinds)
    ok = ids_result.ok and kinds_result.ok
    if not ok:
        _print_json({"ids": ids_result.data, "kinds": kinds_result.data})
    return 0 if ok else 2


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
        pass
    finally:
        capture.stop()
        audio.stop()
        input_tracker.stop()
        window_meta.stop()
        kernel.shutdown()
    return 0


def cmd_devtools_diffusion(args: argparse.Namespace) -> int:
    kernel = Kernel(default_config_paths(), safe_mode=args.safe_mode)
    system = kernel.boot()
    harness = system.get("devtools.diffusion")
    result = harness.run(axis=args.axis, k_variants=args.k, dry_run=args.dry_run)
    _print_json(result)
    kernel.shutdown()
    return 0


def cmd_devtools_ast_ir(args: argparse.Namespace) -> int:
    kernel = Kernel(default_config_paths(), safe_mode=args.safe_mode)
    system = kernel.boot()
    tool = system.get("devtools.ast_ir")
    result = tool.run(scan_root=args.scan_root)
    _print_json(result)
    kernel.shutdown()
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    kernel = Kernel(default_config_paths(), safe_mode=args.safe_mode)
    system = kernel.boot()
    result = run_query(system, args.text)
    _print_json(result)
    kernel.shutdown()
    return 0


def cmd_keys_rotate(args: argparse.Namespace) -> int:
    kernel = Kernel(default_config_paths(), safe_mode=args.safe_mode)
    system = kernel.boot()
    result = rotate_keys(system)
    _print_json(result)
    kernel.shutdown()
    return 0


def cmd_provenance_verify(args: argparse.Namespace) -> int:
    from pathlib import Path

    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config
    from autocapture.pillars.citable import verify_ledger

    if args.path:
        ledger_path = Path(args.path)
    else:
        config = load_config(default_config_paths(), safe_mode=args.safe_mode)
        data_dir = Path(config.get("storage", {}).get("data_dir", "data"))
        ledger_path = data_dir / "ledger.ndjson"

    if not ledger_path.exists():
        print(f"OK ledger_missing: {ledger_path}")
        return 0

    ok, errors = verify_ledger(ledger_path)
    if ok:
        print("OK ledger_verified")
        return 0
    _print_json({"ok": False, "errors": errors, "path": str(ledger_path)})
    return 2


def cmd_research_run(args: argparse.Namespace) -> int:
    from autocapture.config.defaults import default_config_paths as mx_paths
    from autocapture.config.load import load_config as mx_load
    from autocapture.research.runner import ResearchRunner

    config = mx_load(mx_paths(), safe_mode=args.safe_mode)
    if args.safe_mode:
        config.setdefault("plugins", {})["safe_mode"] = True
    runner = ResearchRunner(config)
    result = runner.run_once()
    _print_json(result)
    return 0 if result.get("ok", False) else 1


def _load_user_config(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_user_config(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def cmd_storage_migrate(args: argparse.Namespace) -> int:
    from autocapture.storage.migrate import migrate_data_dir

    paths = default_config_paths()
    config = load_config(paths, safe_mode=args.safe_mode)
    src = args.src or config.get("storage", {}).get("data_dir", "data")
    dst = args.dst
    result = migrate_data_dir(src, dst, dry_run=args.dry_run, verify=not args.no_verify)
    _print_json(asdict(result))
    if args.update_config and not args.dry_run:
        user_cfg = _load_user_config(paths.user_path)
        updates = {"storage": {"data_dir": dst}}
        merged = _deep_merge(user_cfg, updates)
        _write_user_config(paths.user_path, merged)
    return 0


def cmd_storage_forecast(args: argparse.Namespace) -> int:
    from autocapture.storage.forecast import forecast_from_journal

    paths = default_config_paths()
    config = load_config(paths, safe_mode=args.safe_mode)
    data_dir = args.data_dir or config.get("storage", {}).get("data_dir", "data")
    result = forecast_from_journal(str(data_dir))
    _print_json(asdict(result))
    return 0


def cmd_storage_compact(args: argparse.Namespace) -> int:
    from autocapture.storage.compaction import compact_derived

    kernel = Kernel(default_config_paths(), safe_mode=args.safe_mode)
    system = kernel.boot()
    try:
        result = compact_derived(
            system.get("storage.metadata"),
            system.get("storage.media"),
            system.config,
            dry_run=args.dry_run,
            event_builder=system.get("event.builder"),
        )
        _print_json(asdict(result))
    finally:
        kernel.shutdown()
    return 0


def cmd_storage_cleanup(args: argparse.Namespace) -> int:
    import shutil

    target = Path(args.path).resolve()
    if not args.confirm:
        print("Refusing to delete without --confirm")
        return 2
    if str(target) in ("/", str(Path("/").resolve())):
        print("Refusing to delete root path")
        return 2
    if not target.exists():
        print(f"Missing path: {target}")
        return 1
    shutil.rmtree(target)
    print(f"Deleted {target}")
    return 0


def cmd_codex(args: argparse.Namespace) -> int:
    from autocapture.codex.cli import main as codex_main

    return codex_main(args.codex_args)


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
    plugins_list.add_argument("--json", action="store_true", default=False)
    plugins_list.set_defaults(func=cmd_plugins_list)
    plugins_approve = plugins_sub.add_parser("approve")
    plugins_approve.set_defaults(func=cmd_plugins_approve)
    plugins_verify = plugins_sub.add_parser("verify-defaults")
    plugins_verify.set_defaults(func=cmd_plugins_verify_defaults)

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

    provenance = sub.add_parser("provenance")
    provenance_sub = provenance.add_subparsers(dest="provenance_cmd", required=True)
    provenance_verify = provenance_sub.add_parser("verify")
    provenance_verify.add_argument("--path", default="")
    provenance_verify.set_defaults(func=cmd_provenance_verify)

    research = sub.add_parser("research")
    research_sub = research.add_subparsers(dest="research_cmd", required=True)
    research_run = research_sub.add_parser("run")
    research_run.set_defaults(func=cmd_research_run)

    storage = sub.add_parser("storage")
    storage_sub = storage.add_subparsers(dest="storage_cmd", required=True)
    storage_migrate = storage_sub.add_parser("migrate")
    storage_migrate.add_argument("--src", default="")
    storage_migrate.add_argument("--dst", required=True)
    storage_migrate.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=False)
    storage_migrate.add_argument("--no-verify", action="store_true")
    storage_migrate.add_argument("--update-config", action="store_true")
    storage_migrate.set_defaults(func=cmd_storage_migrate)
    storage_forecast = storage_sub.add_parser("forecast")
    storage_forecast.add_argument("--data-dir", default="")
    storage_forecast.set_defaults(func=cmd_storage_forecast)
    storage_compact = storage_sub.add_parser("compact-derived")
    storage_compact.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=False)
    storage_compact.set_defaults(func=cmd_storage_compact)
    storage_cleanup = storage_sub.add_parser("cleanup")
    storage_cleanup.add_argument("--path", required=True)
    storage_cleanup.add_argument("--confirm", action="store_true")
    storage_cleanup.set_defaults(func=cmd_storage_cleanup)

    codex = sub.add_parser("codex")
    codex.add_argument("codex_args", nargs=argparse.REMAINDER)
    codex.set_defaults(func=cmd_codex)

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
