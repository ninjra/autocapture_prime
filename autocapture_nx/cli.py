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

from autocapture_nx.kernel.backup_bundle import create_backup_bundle, restore_backup_bundle

def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def cmd_doctor(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    if getattr(args, "self_test", False):
        result = facade.self_test()
        _print_json(result)
        return 0 if bool(result.get("ok")) else 2
    report = facade.doctor_report()
    if getattr(args, "bundle", False):
        bundle = facade.diagnostics_bundle_create()
        if isinstance(bundle, dict):
            path = str(bundle.get("path") or "")
            sha = str(bundle.get("sha256") or "")
            if path:
                print(f"Diagnostics bundle: {path} sha256={sha}")
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


def cmd_plugins_plan(_args: argparse.Namespace) -> int:
    facade = create_facade()
    _print_json(facade.plugins_plan())
    return 0


def cmd_plugins_capabilities(_args: argparse.Namespace) -> int:
    facade = create_facade()
    _print_json(facade.plugins_capabilities_matrix())
    return 0


def cmd_plugins_install(args: argparse.Namespace) -> int:
    facade = create_facade()
    dry_run = not bool(getattr(args, "apply", False))
    result = facade.plugins_install_local(args.path, dry_run=dry_run)
    _print_json(result)
    return 0 if bool(result.get("ok")) else 2


def cmd_plugins_lock_snapshot(args: argparse.Namespace) -> int:
    facade = create_facade()
    result = facade.plugins_lock_snapshot(str(args.reason))
    _print_json(result)
    return 0 if bool(result.get("ok")) else 2


def cmd_plugins_lock_rollback(args: argparse.Namespace) -> int:
    facade = create_facade()
    result = facade.plugins_lock_rollback(str(args.snapshot_path))
    _print_json(result)
    return 0 if bool(result.get("ok")) else 2


def cmd_plugins_lifecycle(args: argparse.Namespace) -> int:
    facade = create_facade()
    result = facade.plugins_lifecycle_state(str(args.plugin_id))
    _print_json(result)
    return 0 if bool(result.get("ok")) else 2


def cmd_plugins_permissions(args: argparse.Namespace) -> int:
    facade = create_facade()
    result = facade.plugins_permissions_digest(str(args.plugin_id))
    _print_json(result)
    return 0 if bool(result.get("ok")) else 2


def cmd_plugins_permissions_approve(args: argparse.Namespace) -> int:
    facade = create_facade()
    result = facade.plugins_approve_permissions(
        str(args.plugin_id),
        str(args.accept_digest),
        confirm=str(getattr(args, "confirm", "") or ""),
    )
    _print_json(result)
    return 0 if bool(result.get("ok")) else 2


def cmd_plugins_logs(args: argparse.Namespace) -> int:
    facade = create_facade()
    result = facade.plugins_logs(str(args.plugin_id), limit=int(args.limit))
    _print_json(result)
    return 0 if bool(result.get("ok")) else 2


def cmd_plugins_apply(args: argparse.Namespace) -> int:
    facade = create_facade()
    enable = list(getattr(args, "enable", []) or [])
    disable = list(getattr(args, "disable", []) or [])
    result = facade.plugins_apply(str(args.plan_hash), enable=enable, disable=disable)
    _print_json(result)
    return 0 if bool(result.get("ok")) else 2


def cmd_plugins_lock_diff(args: argparse.Namespace) -> int:
    facade = create_facade()
    result = facade.plugins_lock_diff(str(args.a_path), str(args.b_path))
    _print_json(result)
    return 0 if bool(result.get("ok")) else 2


def cmd_plugins_lock_update(args: argparse.Namespace) -> int:
    facade = create_facade()
    result = facade.plugins_update_lock(str(args.plugin_id), reason=str(args.reason))
    _print_json(result)
    return 0 if bool(result.get("ok")) else 2


def cmd_operator_reindex(_args: argparse.Namespace) -> int:
    facade = create_facade()
    result = facade.operator_reindex()
    _print_json(result)
    return 0 if bool(result.get("ok")) else 2


def cmd_operator_vacuum(args: argparse.Namespace) -> int:
    facade = create_facade()
    result = facade.operator_vacuum(include_state=bool(getattr(args, "include_state", True)))
    _print_json(result)
    return 0 if bool(result.get("ok")) else 2


def cmd_operator_quarantine(args: argparse.Namespace) -> int:
    facade = create_facade()
    result = facade.operator_quarantine(str(args.plugin_id), reason=str(args.reason))
    _print_json(result)
    return 0 if bool(result.get("ok")) else 2


def cmd_operator_rollback_locks(args: argparse.Namespace) -> int:
    facade = create_facade()
    result = facade.operator_rollback_locks(str(args.snapshot_path))
    _print_json(result)
    return 0 if bool(result.get("ok")) else 2


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


def cmd_consent_status(args: argparse.Namespace) -> int:
    config, _paths = _load_config_for_backup(args.data_dir, args.config_dir, safe_mode=args.safe_mode)
    storage = config.get("storage", {}) if isinstance(config, dict) else {}
    data_dir = str(storage.get("data_dir", "data"))
    from autocapture_nx.kernel.consent import load_capture_consent

    consent = load_capture_consent(data_dir=data_dir)
    _print_json({"ok": True, "data_dir": data_dir, "capture": consent.to_dict()})
    return 0


def cmd_consent_accept(args: argparse.Namespace) -> int:
    config, _paths = _load_config_for_backup(args.data_dir, args.config_dir, safe_mode=args.safe_mode)
    storage = config.get("storage", {}) if isinstance(config, dict) else {}
    data_dir = str(storage.get("data_dir", "data"))
    from autocapture_nx.kernel.consent import accept_capture_consent

    consent = accept_capture_consent(data_dir=data_dir)
    append_audit_event(
        action="consent.capture.accept",
        actor="cli.consent",
        outcome="success",
        details={"data_dir": data_dir, "accepted_ts_utc": consent.accepted_ts_utc},
    )
    _print_json({"ok": True, "data_dir": data_dir, "capture": consent.to_dict()})
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    facade = create_facade(persistent=True, safe_mode=args.safe_mode, auto_start_capture=False)
    facade.run_start()
    duration_s = int(getattr(args, "duration_s", 0) or 0)
    status_interval_s = int(getattr(args, "status_interval_s", 0) or 0)
    if duration_s > 0:
        print(f"Capture running for up to {duration_s}s. Press Ctrl+C to stop early.")
    else:
        print("Capture running. Press Ctrl+C to stop.")
    try:
        import time
        started = time.monotonic()
        last_status = started
        while True:
            time.sleep(1)
            now = time.monotonic()
            if duration_s > 0 and (now - started) >= duration_s:
                break
            if status_interval_s > 0 and (now - last_status) >= status_interval_s:
                last_status = now
                try:
                    result = facade.doctor_report()
                except Exception:
                    result = None
                if isinstance(result, dict):
                    summary_raw = result.get("summary")
                    summary: dict[str, Any] = summary_raw if isinstance(summary_raw, dict) else {}
                    code = str(summary.get("code") or "")
                    msg = str(summary.get("message") or "")
                    print(f"[status] code={code} message={msg[:120]}")
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


def cmd_status(args: argparse.Namespace) -> int:
    facade = create_facade(safe_mode=args.safe_mode)
    payload = facade.status()
    _print_json(payload)
    # Non-zero exit helps scripts/soak harnesses detect degraded mode.
    return 3 if bool(payload.get("safe_mode")) else 0


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


def _load_config_for_backup(data_dir: str, config_dir: str, *, safe_mode: bool) -> tuple[dict, Any]:
    if data_dir:
        os.environ["AUTOCAPTURE_DATA_DIR"] = data_dir
    if config_dir:
        os.environ["AUTOCAPTURE_CONFIG_DIR"] = config_dir
    paths = default_config_paths()
    config = load_config(paths, safe_mode=safe_mode)
    return config, paths


def cmd_backup_create(args: argparse.Namespace) -> int:
    details: dict[str, Any] = {"bundle_path": str(args.out), "include_data": bool(args.include_data)}
    try:
        config, paths = _load_config_for_backup(args.data_dir, args.config_dir, safe_mode=args.safe_mode)
        storage = config.get("storage", {}) if isinstance(config, dict) else {}
        crypto = storage.get("crypto", {}) if isinstance(storage, dict) else {}
        data_dir = str(storage.get("data_dir", "data"))
        cfg_dir = str(Path(paths.user_path).resolve().parent)
        encryption_required = bool(storage.get("encryption_required", False))

        include_keys = args.keys
        if include_keys is None:
            include_keys = bool(encryption_required)
        include_keys = bool(include_keys)

        passphrase = ""
        if include_keys:
            passphrase = _prompt_passphrase(args.passphrase)

        report = create_backup_bundle(
            output_path=args.out,
            config_dir=cfg_dir,
            data_dir=data_dir,
            include_data=bool(args.include_data),
            include_keyring_bundle=include_keys,
            keyring_bundle_passphrase=passphrase if include_keys else None,
            keyring_backend=str(crypto.get("keyring_backend", "auto") or "auto"),
            keyring_credential_name=str(crypto.get("keyring_credential_name", "autocapture.keyring") or "autocapture.keyring"),
            require_key_protection=bool(encryption_required and os.name == "nt"),
            keyring_path=str(crypto.get("keyring_path", Path(data_dir) / "vault" / "keyring.json")),
            legacy_root_key_path=str(crypto.get("root_key_path", Path(data_dir) / "vault" / "root.key")),
            overwrite=bool(args.overwrite),
        )
        details.update({"ok": bool(report.get("ok")), "entries": int(report.get("entries", 0) or 0)})
        append_audit_event(action="backup.create", actor="cli.backup", outcome="success" if report.get("ok") else "error", details=details)
        _print_json(report)
        return 0 if report.get("ok") else 2
    except Exception as exc:
        details["error"] = str(exc)
        append_audit_event(action="backup.create", actor="cli.backup", outcome="error", details=details)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def cmd_backup_restore(args: argparse.Namespace) -> int:
    details: dict[str, Any] = {"bundle_path": str(args.bundle)}
    try:
        config, paths = _load_config_for_backup(args.data_dir, args.config_dir, safe_mode=args.safe_mode)
        storage = config.get("storage", {}) if isinstance(config, dict) else {}
        data_dir = str(storage.get("data_dir", "data"))
        cfg_dir = str(Path(paths.user_path).resolve().parent)

        passphrase = args.passphrase or ""
        if args.restore_keys:
            passphrase = _prompt_passphrase(passphrase)

        report = restore_backup_bundle(
            bundle_path=args.bundle,
            config_dir=cfg_dir,
            data_dir=data_dir,
            keyring_bundle_passphrase=passphrase if args.restore_keys else None,
            restore_keyring_bundle=bool(args.restore_keys),
            overwrite=bool(args.overwrite),
        )
        details.update({"ok": bool(report.get("ok")), "extracted": int(report.get("extracted", 0) or 0)})
        append_audit_event(action="backup.restore", actor="cli.backup", outcome="success" if report.get("ok") else "error", details=details)
        _print_json(report)
        return 0 if report.get("ok") else 2
    except Exception as exc:
        details["error"] = str(exc)
        append_audit_event(action="backup.restore", actor="cli.backup", outcome="error", details=details)
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
    doctor.add_argument("--bundle", action="store_true", help="Create a diagnostics bundle zip")
    doctor.add_argument("--self-test", action="store_true", help="Run a lightweight offline self-test")
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
    plugins_plan = plugins_sub.add_parser("plan")
    plugins_plan.set_defaults(func=cmd_plugins_plan)
    plugins_caps = plugins_sub.add_parser("capabilities")
    plugins_caps.set_defaults(func=cmd_plugins_capabilities)
    plugins_install = plugins_sub.add_parser("install")
    plugins_install.add_argument("path")
    plugins_install.add_argument("--apply", action="store_true", default=False, help="Apply install (default is dry-run)")
    plugins_install.set_defaults(func=cmd_plugins_install)
    plugins_lock = plugins_sub.add_parser("lock")
    plugins_lock_sub = plugins_lock.add_subparsers(dest="lock_cmd", required=True)
    plugins_lock_snapshot = plugins_lock_sub.add_parser("snapshot")
    plugins_lock_snapshot.add_argument("--reason", default="snapshot")
    plugins_lock_snapshot.set_defaults(func=cmd_plugins_lock_snapshot)
    plugins_lock_rollback = plugins_lock_sub.add_parser("rollback")
    plugins_lock_rollback.add_argument("snapshot_path")
    plugins_lock_rollback.set_defaults(func=cmd_plugins_lock_rollback)
    plugins_lock_diff = plugins_lock_sub.add_parser("diff")
    plugins_lock_diff.add_argument("a_path")
    plugins_lock_diff.add_argument("b_path")
    plugins_lock_diff.set_defaults(func=cmd_plugins_lock_diff)
    plugins_lock_update = plugins_lock_sub.add_parser("update")
    plugins_lock_update.add_argument("plugin_id")
    plugins_lock_update.add_argument("--reason", default="update")
    plugins_lock_update.set_defaults(func=cmd_plugins_lock_update)
    plugins_lifecycle = plugins_sub.add_parser("lifecycle")
    plugins_lifecycle.add_argument("plugin_id")
    plugins_lifecycle.set_defaults(func=cmd_plugins_lifecycle)
    plugins_permissions = plugins_sub.add_parser("permissions")
    plugins_permissions.add_argument("plugin_id")
    plugins_permissions.set_defaults(func=cmd_plugins_permissions)
    plugins_permissions_approve = plugins_sub.add_parser("approve-permissions")
    plugins_permissions_approve.add_argument("plugin_id")
    plugins_permissions_approve.add_argument("--accept-digest", required=True)
    plugins_permissions_approve.add_argument(
        "--confirm",
        default="",
        help="If required, pass the exact confirmation string returned in the approval error (e.g. APPROVE:<plugin_id>).",
    )
    plugins_permissions_approve.set_defaults(func=cmd_plugins_permissions_approve)
    plugins_apply = plugins_sub.add_parser("apply")
    plugins_apply.add_argument("--plan-hash", required=True)
    plugins_apply.add_argument("--enable", action="append", default=[], help="Plugin id to enable (repeatable).")
    plugins_apply.add_argument("--disable", action="append", default=[], help="Plugin id to disable (repeatable).")
    plugins_apply.set_defaults(func=cmd_plugins_apply)
    plugins_logs = plugins_sub.add_parser("logs")
    plugins_logs.add_argument("plugin_id")
    plugins_logs.add_argument("--limit", type=int, default=80)
    plugins_logs.set_defaults(func=cmd_plugins_logs)
    plugins_verify = plugins_sub.add_parser("verify-defaults")
    plugins_verify.set_defaults(func=cmd_plugins_verify_defaults)

    operator = sub.add_parser("operator")
    operator_sub = operator.add_subparsers(dest="operator_cmd", required=True)
    op_reindex = operator_sub.add_parser("reindex")
    op_reindex.set_defaults(func=cmd_operator_reindex)
    op_vacuum = operator_sub.add_parser("vacuum")
    op_vacuum.add_argument("--include-state", action=argparse.BooleanOptionalAction, default=True)
    op_vacuum.set_defaults(func=cmd_operator_vacuum)
    op_quarantine = operator_sub.add_parser("quarantine")
    op_quarantine.add_argument("plugin_id")
    op_quarantine.add_argument("--reason", default="operator_quarantine")
    op_quarantine.set_defaults(func=cmd_operator_quarantine)
    op_rollback = operator_sub.add_parser("rollback-locks")
    op_rollback.add_argument("snapshot_path")
    op_rollback.set_defaults(func=cmd_operator_rollback_locks)

    consent = sub.add_parser("consent")
    consent_sub = consent.add_subparsers(dest="consent_cmd", required=True)
    consent_status = consent_sub.add_parser("status")
    consent_status.add_argument("--data-dir", default="", help="Override AUTOCAPTURE_DATA_DIR")
    consent_status.add_argument("--config-dir", default="", help="Override AUTOCAPTURE_CONFIG_DIR")
    consent_status.set_defaults(func=cmd_consent_status)
    consent_accept = consent_sub.add_parser("accept")
    consent_accept.add_argument("--data-dir", default="", help="Override AUTOCAPTURE_DATA_DIR")
    consent_accept.add_argument("--config-dir", default="", help="Override AUTOCAPTURE_CONFIG_DIR")
    consent_accept.set_defaults(func=cmd_consent_accept)

    tray = sub.add_parser("tray")
    tray.set_defaults(func=cmd_tray)

    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--duration-s", type=int, default=0, help="Stop after N seconds (0=run until Ctrl+C)")
    run_cmd.add_argument(
        "--status-interval-s",
        type=int,
        default=0,
        help="Print doctor status every N seconds (0=disabled)",
    )
    run_cmd.set_defaults(func=cmd_run)

    status_cmd = sub.add_parser("status")
    status_cmd.set_defaults(func=cmd_status)

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

    backup = sub.add_parser("backup")
    backup_sub = backup.add_subparsers(dest="backup_cmd", required=True)
    backup_create = backup_sub.add_parser("create")
    backup_create.add_argument("--out", required=True, help="Output bundle path (zip)")
    backup_create.add_argument("--include-data", action=argparse.BooleanOptionalAction, default=False)
    backup_create.add_argument("--keys", action=argparse.BooleanOptionalAction, default=None, help="Include portable keyring bundle")
    backup_create.add_argument("--passphrase", default="", help="Keyring bundle passphrase (prompted if empty)")
    backup_create.add_argument("--overwrite", action=argparse.BooleanOptionalAction, default=False)
    backup_create.add_argument("--data-dir", default="", help="Override AUTOCAPTURE_DATA_DIR")
    backup_create.add_argument("--config-dir", default="", help="Override AUTOCAPTURE_CONFIG_DIR")
    backup_create.set_defaults(func=cmd_backup_create)
    backup_restore = backup_sub.add_parser("restore")
    backup_restore.add_argument("--bundle", required=True, help="Input bundle path (zip)")
    backup_restore.add_argument("--restore-keys", action=argparse.BooleanOptionalAction, default=True)
    backup_restore.add_argument("--passphrase", default="", help="Keyring bundle passphrase (prompted if empty)")
    backup_restore.add_argument("--overwrite", action=argparse.BooleanOptionalAction, default=False)
    backup_restore.add_argument("--data-dir", default="", help="Override AUTOCAPTURE_DATA_DIR")
    backup_restore.add_argument("--config-dir", default="", help="Override AUTOCAPTURE_CONFIG_DIR")
    backup_restore.set_defaults(func=cmd_backup_restore)

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
