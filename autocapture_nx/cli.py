"""Command line interface for Autocapture NX."""

from __future__ import annotations

import argparse
import json
import os
import sys
from getpass import getpass
from dataclasses import asdict
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.config import load_config
from autocapture_nx.kernel.audit import append_audit_event
from autocapture_nx.kernel.errors import AutocaptureError
from autocapture_nx.kernel.keyring import KeyRing, export_keyring_bundle, import_keyring_bundle
from autocapture_nx.kernel.loader import default_config_paths
from autocapture_nx.ux.facade import create_facade


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def cmd_doctor(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    report = facade.doctor_report()
    ok = bool(report.get("ok"))
    for check in report.get("checks", []):
        ok_flag = bool(check.get("ok")) if isinstance(check, dict) else False
        status = "OK" if ok_flag else "FAIL"
        name = check.get("name") if isinstance(check, dict) else "unknown"
        detail = check.get("detail") if isinstance(check, dict) else ""
        print(f"{status} {name}: {detail}")
    return 0 if ok else 2


def cmd_config_show(_args: argparse.Namespace) -> int:
    facade = create_facade()
    _print_json(facade.config_get())
    return 0


def cmd_config_reset(_args: argparse.Namespace) -> int:
    facade = create_facade()
    facade.config_reset()
    print("User config reset to defaults")
    return 0


def cmd_config_restore(_args: argparse.Namespace) -> int:
    facade = create_facade()
    facade.config_restore()
    print("User config restored from backup")
    return 0


def cmd_plugins_list(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    payload = facade.plugins_list()
    _print_json(payload)
    return 0


def cmd_plugins_approve(_args: argparse.Namespace) -> int:
    facade = create_facade()
    facade.plugins_approve()
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


def cmd_tray(_args: argparse.Namespace) -> int:
    from autocapture_nx.tray import main as tray_main

    return tray_main()


def cmd_run(args: argparse.Namespace) -> int:
    facade = create_facade(persistent=True, safe_mode=args.safe_mode, auto_start_capture=False)
    facade.run_start()
    print("Capture running. Press Ctrl+C to stop.")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        facade.run_stop()
        facade.shutdown()
    return 0


def cmd_devtools_diffusion(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.devtools_diffusion(axis=args.axis, k_variants=args.k, dry_run=args.dry_run)
    _print_json(result)
    return 0


def cmd_devtools_ast_ir(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.devtools_ast_ir(scan_root=args.scan_root)
    _print_json(result)
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.query(args.text)
    _print_json(result)
    return 0


def cmd_state_jepa_approve(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.state_jepa_approve(args.model_version, args.training_run_id)
    _print_json(result)
    return 0


def cmd_state_jepa_approve_latest(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.state_jepa_approve_latest(include_archived=args.archived)
    _print_json(result)
    return 0


def cmd_state_jepa_promote(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.state_jepa_promote(args.model_version, args.training_run_id)
    _print_json(result)
    return 0


def cmd_state_jepa_report(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    model_version = args.model_version
    training_run_id = args.training_run_id
    if args.latest:
        listing = facade.state_jepa_list(include_archived=True)
        models = listing.get("models") if isinstance(listing, dict) else []
        active = None
        if isinstance(models, list):
            for item in models:
                if isinstance(item, dict) and item.get("active"):
                    active = item
                    break
        if active is None and isinstance(models, list) and models:
            active = models[0] if isinstance(models[0], dict) else None
        if active:
            model_version = str(active.get("model_version") or "")
            training_run_id = str(active.get("training_run_id") or "")
    if not model_version or not training_run_id:
        _print_json({"ok": False, "error": "model_version_and_training_run_id_required"})
        return 1
    result = facade.state_jepa_report(model_version, training_run_id)
    _print_json(result)
    return 0


def cmd_state_jepa_list(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.state_jepa_list(include_archived=args.archived)
    _print_json(result)
    return 0


def cmd_state_jepa_archive(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.state_jepa_archive(dry_run=args.dry_run)
    _print_json(result)
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.enrich(force=True)
    _print_json(result)
    return 0


def cmd_keys_rotate(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.keys_rotate()
    _print_json(result)
    return 0


def _load_crypto_config(data_dir: str, config_dir: str, *, safe_mode: bool) -> dict:
    if data_dir:
        os.environ["AUTOCAPTURE_DATA_DIR"] = data_dir
    if config_dir:
        os.environ["AUTOCAPTURE_CONFIG_DIR"] = config_dir
    paths = default_config_paths()
    config = load_config(paths, safe_mode=safe_mode)
    storage = config.get("storage", {}) if isinstance(config, dict) else {}
    crypto = storage.get("crypto", {}) if isinstance(storage, dict) else {}
    return {
        "keyring_path": str(crypto.get("keyring_path", "data/vault/keyring.json")),
        "root_key_path": str(crypto.get("root_key_path", "data/vault/root.key")),
        "backend": str(crypto.get("keyring_backend", "auto")),
        "credential_name": str(crypto.get("keyring_credential_name", "autocapture.keyring")),
        "encryption_required": bool(storage.get("encryption_required", False)),
    }


def _prompt_passphrase(value: str) -> str:
    if value:
        return value
    return getpass("Keyring bundle passphrase: ")


def cmd_keys_export(args: argparse.Namespace) -> int:
    details: dict[str, Any] = {"bundle_path": str(args.out)}
    try:
        crypto = _load_crypto_config(args.data_dir, args.config_dir, safe_mode=args.safe_mode)
        require_protection = bool(crypto["encryption_required"] and os.name == "nt")
        details.update(
            {
                "keyring_path": crypto["keyring_path"],
                "backend": crypto["backend"],
                "require_protection": require_protection,
            }
        )
        keyring = KeyRing.load(
            crypto["keyring_path"],
            legacy_root_path=crypto["root_key_path"],
            require_protection=require_protection,
            backend=crypto["backend"],
            credential_name=crypto["credential_name"],
        )
        passphrase = _prompt_passphrase(args.passphrase)
        export_keyring_bundle(keyring, path=str(args.out), passphrase=passphrase)
        append_audit_event(
            action="keyring.export",
            actor="cli.keys",
            outcome="success",
            details=details,
        )
        print(f"OK: keyring bundle written to {args.out}")
        return 0
    except Exception as exc:
        details["error"] = str(exc)
        append_audit_event(
            action="keyring.export",
            actor="cli.keys",
            outcome="error",
            details=details,
        )
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def cmd_keys_import(args: argparse.Namespace) -> int:
    details: dict[str, Any] = {"bundle_path": str(args.bundle)}
    try:
        crypto = _load_crypto_config(args.data_dir, args.config_dir, safe_mode=args.safe_mode)
        require_protection = bool(crypto["encryption_required"] and os.name == "nt")
        details.update(
            {
                "keyring_path": crypto["keyring_path"],
                "backend": crypto["backend"],
                "require_protection": require_protection,
            }
        )
        passphrase = _prompt_passphrase(args.passphrase)
        import_keyring_bundle(
            path=str(args.bundle),
            passphrase=passphrase,
            keyring_path=crypto["keyring_path"],
            require_protection=require_protection,
            backend=crypto["backend"],
            credential_name=crypto["credential_name"],
        )
        append_audit_event(
            action="keyring.import",
            actor="cli.keys",
            outcome="success",
            details=details,
        )
        print(f"OK: keyring bundle imported into {crypto['keyring_path']}")
        return 0
    except Exception as exc:
        details["error"] = str(exc)
        append_audit_event(
            action="keyring.import",
            actor="cli.keys",
            outcome="error",
            details=details,
        )
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def cmd_provenance_verify(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.verify_ledger(args.path)
    if result.get("missing"):
        print(f"OK ledger_missing: {result.get('path')}")
        return 0
    if result.get("ok"):
        print("OK ledger_verified")
        return 0
    _print_json(result)
    return 2


def cmd_verify_ledger(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.verify_ledger(args.path)
    if result.get("missing"):
        print(f"OK ledger_missing: {result.get('path')}")
        return 0
    if result.get("ok"):
        print("OK ledger_verified")
        return 0
    _print_json(result)
    return 2


def cmd_verify_anchors(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.verify_anchors(args.path)
    if result.get("ok"):
        print("OK anchors_verified")
        return 0
    _print_json(result)
    return 2


def cmd_verify_evidence(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.verify_evidence()
    if result.get("ok"):
        print("OK evidence_verified")
        return 0
    _print_json(result)
    return 2


def cmd_integrity_scan(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.integrity_scan()
    _print_json(result)
    return 0 if result.get("ok") else 2


def cmd_verify_archive(args: argparse.Namespace) -> int:
    from autocapture.storage.archive import verify_archive

    path = str(args.path or "").strip()
    if not path:
        _print_json({"ok": False, "error": "missing_archive_path"})
        return 1
    ok, issues = verify_archive(path)
    if ok:
        print("OK archive_verified")
        return 0
    _print_json({"ok": False, "issues": issues})
    return 2


def cmd_citations_resolve(args: argparse.Namespace) -> int:
    try:
        payload = _load_json_payload(args.path, args.json)
        citations = _extract_citations(payload)
    except Exception as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 1
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.citations_resolve(citations)
    _print_json(result)
    return 0 if result.get("ok") else 2


def cmd_citations_verify(args: argparse.Namespace) -> int:
    try:
        payload = _load_json_payload(args.path, args.json)
        citations = _extract_citations(payload)
    except Exception as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 1
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.citations_verify(citations)
    if result.get("ok"):
        print("OK citations_verified")
        return 0
    _print_json(result)
    return 2


def cmd_proof_export(args: argparse.Namespace) -> int:
    citations = None
    if args.citations:
        try:
            payload = _load_json_payload(args.citations, None)
            citations = _extract_citations(payload)
        except Exception as exc:
            _print_json({"ok": False, "error": str(exc)})
            return 1
    evidence_ids = list(args.evidence_id or [])
    if not evidence_ids and not citations:
        _print_json({"ok": False, "error": "missing_evidence_or_citations"})
        return 1
    facade = create_facade(safe_mode=args.safe_mode)
    report = facade.export_proof_bundle(evidence_ids=evidence_ids, output_path=args.out, citations=citations)
    _print_json(report)
    return 0 if report.get("ok") else 2


def cmd_replay(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    report = facade.replay_proof_bundle(args.bundle)
    _print_json(report)
    return 0 if report.get("ok") else 2


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


def _load_json_payload(path: str | None, raw_json: str | None):
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    if raw_json:
        return json.loads(raw_json)
    data = sys.stdin.read()
    if data.strip():
        return json.loads(data)
    raise ValueError("missing_json_payload")


def _extract_citations(payload: object) -> list[dict]:
    if isinstance(payload, dict) and "citations" in payload:
        citations = payload.get("citations")
    else:
        citations = payload
    if not isinstance(citations, list):
        raise ValueError("citations_not_list")
    return citations


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


def cmd_storage_migrate_metadata(args: argparse.Namespace) -> int:
    from plugins.builtin.storage_sqlcipher.plugin import migrate_metadata_json_to_sqlcipher

    paths = default_config_paths()
    config = load_config(paths, safe_mode=args.safe_mode)
    src = args.src or None
    dst = args.dst or None
    result = migrate_metadata_json_to_sqlcipher(
        config,
        src_dir=src,
        dst_path=dst,
        dry_run=args.dry_run,
    )
    _print_json(asdict(result))
    return 0


def cmd_storage_forecast(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.storage_forecast(args.data_dir)
    _print_json(result)
    return 0


def cmd_storage_compact(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    result = facade.storage_compact(dry_run=args.dry_run)
    _print_json(result)
    return 0


def cmd_storage_cleanup(args: argparse.Namespace) -> int:
    _ = args
    print("Storage cleanup disabled by policy (no deletion)")
    return 2


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

    tray = sub.add_parser("tray")
    tray.set_defaults(func=cmd_tray)

    run_cmd = sub.add_parser("run")
    run_cmd.set_defaults(func=cmd_run)

    query_cmd = sub.add_parser("query")
    query_cmd.add_argument("text")
    query_cmd.set_defaults(func=cmd_query)

    state = sub.add_parser("state")
    state_sub = state.add_subparsers(dest="state_cmd", required=True)
    jepa = state_sub.add_parser("jepa")
    jepa_sub = jepa.add_subparsers(dest="jepa_cmd", required=True)
    jepa_approve = jepa_sub.add_parser("approve")
    jepa_approve.add_argument("--model-version", required=True)
    jepa_approve.add_argument("--training-run-id", required=True)
    jepa_approve.set_defaults(func=cmd_state_jepa_approve)
    jepa_approve_latest = jepa_sub.add_parser("approve-latest")
    jepa_approve_latest.add_argument("--archived", action=argparse.BooleanOptionalAction, default=False)
    jepa_approve_latest.set_defaults(func=cmd_state_jepa_approve_latest)
    jepa_promote = jepa_sub.add_parser("promote")
    jepa_promote.add_argument("--model-version", required=True)
    jepa_promote.add_argument("--training-run-id", required=True)
    jepa_promote.set_defaults(func=cmd_state_jepa_promote)
    jepa_report = jepa_sub.add_parser("report")
    jepa_report.add_argument("--model-version")
    jepa_report.add_argument("--training-run-id")
    jepa_report.add_argument("--latest", action="store_true", default=False)
    jepa_report.set_defaults(func=cmd_state_jepa_report)
    jepa_list = jepa_sub.add_parser("list")
    jepa_list.add_argument("--archived", action=argparse.BooleanOptionalAction, default=True)
    jepa_list.set_defaults(func=cmd_state_jepa_list)
    jepa_archive = jepa_sub.add_parser("archive")
    jepa_archive.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=False)
    jepa_archive.set_defaults(func=cmd_state_jepa_archive)

    enrich_cmd = sub.add_parser("enrich")
    enrich_cmd.set_defaults(func=cmd_enrich)

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
    keys_export = keys_sub.add_parser("export")
    keys_export.add_argument("--out", required=True, help="Output bundle path (JSON)")
    keys_export.add_argument("--passphrase", default="", help="Bundle passphrase (prompted if empty)")
    keys_export.add_argument("--data-dir", default="", help="Override AUTOCAPTURE_DATA_DIR")
    keys_export.add_argument("--config-dir", default="", help="Override AUTOCAPTURE_CONFIG_DIR")
    keys_export.set_defaults(func=cmd_keys_export)
    keys_import = keys_sub.add_parser("import")
    keys_import.add_argument("--bundle", required=True, help="Input bundle path (JSON)")
    keys_import.add_argument("--passphrase", default="", help="Bundle passphrase (prompted if empty)")
    keys_import.add_argument("--data-dir", default="", help="Override AUTOCAPTURE_DATA_DIR")
    keys_import.add_argument("--config-dir", default="", help="Override AUTOCAPTURE_CONFIG_DIR")
    keys_import.set_defaults(func=cmd_keys_import)

    provenance = sub.add_parser("provenance")
    provenance_sub = provenance.add_subparsers(dest="provenance_cmd", required=True)
    provenance_verify = provenance_sub.add_parser("verify")
    provenance_verify.add_argument("--path", default="")
    provenance_verify.set_defaults(func=cmd_provenance_verify)

    citations = sub.add_parser("citations")
    citations_sub = citations.add_subparsers(dest="citations_cmd", required=True)
    citations_resolve = citations_sub.add_parser("resolve")
    citations_resolve.add_argument("--path", default="")
    citations_resolve.add_argument("--json", default="")
    citations_resolve.set_defaults(func=cmd_citations_resolve)
    citations_verify = citations_sub.add_parser("verify")
    citations_verify.add_argument("--path", default="")
    citations_verify.add_argument("--json", default="")
    citations_verify.set_defaults(func=cmd_citations_verify)

    verify = sub.add_parser("verify")
    verify_sub = verify.add_subparsers(dest="verify_cmd", required=True)
    verify_ledger = verify_sub.add_parser("ledger")
    verify_ledger.add_argument("--path", default="")
    verify_ledger.set_defaults(func=cmd_verify_ledger)
    verify_anchors = verify_sub.add_parser("anchors")
    verify_anchors.add_argument("--path", default="")
    verify_anchors.set_defaults(func=cmd_verify_anchors)
    verify_evidence = verify_sub.add_parser("evidence")
    verify_evidence.set_defaults(func=cmd_verify_evidence)
    verify_archive = verify_sub.add_parser("archive")
    verify_archive.add_argument("--path", required=True)
    verify_archive.set_defaults(func=cmd_verify_archive)

    integrity = sub.add_parser("integrity")
    integrity_sub = integrity.add_subparsers(dest="integrity_cmd", required=True)
    integrity_scan = integrity_sub.add_parser("scan")
    integrity_scan.set_defaults(func=cmd_integrity_scan)

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
    storage_migrate_meta = storage_sub.add_parser("migrate-metadata")
    storage_migrate_meta.add_argument("--src", default="")
    storage_migrate_meta.add_argument("--dst", default="")
    storage_migrate_meta.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=False)
    storage_migrate_meta.set_defaults(func=cmd_storage_migrate_metadata)
    storage_forecast = storage_sub.add_parser("forecast")
    storage_forecast.add_argument("--data-dir", default="")
    storage_forecast.set_defaults(func=cmd_storage_forecast)
    storage_compact = storage_sub.add_parser("compact-derived")
    storage_compact.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=False)
    storage_compact.set_defaults(func=cmd_storage_compact)
    # storage cleanup intentionally omitted: deletion is disabled by policy

    proof = sub.add_parser("proof")
    proof_sub = proof.add_subparsers(dest="proof_cmd", required=True)
    proof_export = proof_sub.add_parser("export")
    proof_export.add_argument("--out", required=True)
    proof_export.add_argument("--evidence-id", action="append", default=[])
    proof_export.add_argument("--citations", default="")
    proof_export.set_defaults(func=cmd_proof_export)

    replay = sub.add_parser("replay")
    replay.add_argument("--bundle", required=True)
    replay.set_defaults(func=cmd_replay)

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
