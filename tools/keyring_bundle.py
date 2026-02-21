"""Export/import keyring bundles for portable backups."""

from __future__ import annotations

import argparse
import os
from getpass import getpass

from autocapture_nx.kernel.loader import default_config_paths
from autocapture_nx.kernel.config import load_config
from autocapture_nx.kernel.keyring import KeyRing, export_keyring_bundle, import_keyring_bundle
from autocapture_nx.kernel.audit import append_audit_event


def _load_config(data_dir: str | None, config_dir: str | None) -> dict:
    if data_dir:
        os.environ["AUTOCAPTURE_DATA_DIR"] = data_dir
    if config_dir:
        os.environ["AUTOCAPTURE_CONFIG_DIR"] = config_dir
    paths = default_config_paths()
    return load_config(paths, safe_mode=False)


def _resolve_crypto(cfg: dict) -> dict:
    storage = cfg.get("storage", {}) if isinstance(cfg, dict) else {}
    crypto = storage.get("crypto", {}) if isinstance(storage, dict) else {}
    return {
        "keyring_path": str(crypto.get("keyring_path", "data/vault/keyring.json")),
        "root_key_path": str(crypto.get("root_key_path", "data/vault/root.key")),
        "backend": str(crypto.get("keyring_backend", "auto")),
        "credential_name": str(crypto.get("keyring_credential_name", "autocapture.keyring")),
        "encryption_required": bool(storage.get("encryption_required", False)),
    }


def _prompt_passphrase(arg: str | None) -> str:
    if arg:
        return arg
    return getpass("Keyring bundle passphrase: ")


def cmd_export(args: argparse.Namespace) -> int:
    cfg = _load_config(args.data_dir, args.config_dir)
    crypto = _resolve_crypto(cfg)
    require_protection = bool(crypto["encryption_required"] and os.name == "nt")
    details = {
        "bundle_path": str(args.out),
        "keyring_path": crypto["keyring_path"],
        "backend": crypto["backend"],
        "require_protection": require_protection,
    }
    try:
        keyring = KeyRing.load(
            crypto["keyring_path"],
            legacy_root_path=crypto["root_key_path"],
            require_protection=require_protection,
            backend=crypto["backend"],
            credential_name=crypto["credential_name"],
        )
        passphrase = _prompt_passphrase(args.passphrase)
        export_keyring_bundle(keyring, path=args.out, passphrase=passphrase)
        append_audit_event(action="keyring.export", actor="tools.keyring_bundle", outcome="success", details=details)
        print(f"OK: keyring bundle written to {args.out}")
        return 0
    except Exception as exc:
        details["error"] = str(exc)
        append_audit_event(action="keyring.export", actor="tools.keyring_bundle", outcome="error", details=details)
        raise


def cmd_import(args: argparse.Namespace) -> int:
    cfg = _load_config(args.data_dir, args.config_dir)
    crypto = _resolve_crypto(cfg)
    require_protection = bool(crypto["encryption_required"] and os.name == "nt")
    details = {
        "bundle_path": str(args.bundle),
        "keyring_path": crypto["keyring_path"],
        "backend": crypto["backend"],
        "require_protection": require_protection,
    }
    try:
        passphrase = _prompt_passphrase(args.passphrase)
        import_keyring_bundle(
            path=args.bundle,
            passphrase=passphrase,
            keyring_path=crypto["keyring_path"],
            require_protection=require_protection,
            backend=crypto["backend"],
            credential_name=crypto["credential_name"],
        )
        append_audit_event(action="keyring.import", actor="tools.keyring_bundle", outcome="success", details=details)
        print(f"OK: keyring bundle imported into {crypto['keyring_path']}")
        return 0
    except Exception as exc:
        details["error"] = str(exc)
        append_audit_event(action="keyring.import", actor="tools.keyring_bundle", outcome="error", details=details)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="", help="Override AUTOCAPTURE_DATA_DIR")
    parser.add_argument("--config-dir", default="", help="Override AUTOCAPTURE_CONFIG_DIR")
    sub = parser.add_subparsers(dest="cmd", required=True)

    exp = sub.add_parser("export")
    exp.add_argument("--out", required=True, help="Output bundle path (JSON)")
    exp.add_argument("--passphrase", default="", help="Bundle passphrase (prompted if empty)")
    exp.set_defaults(func=cmd_export)

    imp = sub.add_parser("import")
    imp.add_argument("--bundle", required=True, help="Input bundle path (JSON)")
    imp.add_argument("--passphrase", default="", help="Bundle passphrase (prompted if empty)")
    imp.set_defaults(func=cmd_import)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
