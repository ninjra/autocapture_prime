"""Portable backup bundle create/restore with integrity checks.

This is distinct from proof bundles:
- Backup bundles are raw-first and intended for operator recovery/migration.
- Proof bundles are citation-focused and may be smaller/scoped.

Policy: no deletion. Restore archives any conflicting destination paths.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from autocapture_nx.kernel.atomic_write import atomic_write_text
from autocapture_nx.kernel.keyring import KeyRing, export_keyring_bundle, import_keyring_bundle
from autocapture_nx.kernel.paths import repo_root


_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)  # keep zip entry timestamps stable


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip_write_bytes(zf: ZipFile, arcname: str, data: bytes) -> None:
    info = ZipInfo(arcname)
    info.date_time = _ZIP_EPOCH
    info.compress_type = ZIP_DEFLATED
    zf.writestr(info, data)


def _zip_write_file(zf: ZipFile, arcname: str, path: Path) -> None:
    # Use a stable ZipInfo to avoid mtime churn across runs.
    info = ZipInfo(arcname)
    info.date_time = _ZIP_EPOCH
    info.compress_type = ZIP_DEFLATED
    with zf.open(info, "w") as dst, path.open("rb") as src:
        shutil.copyfileobj(src, dst, length=1024 * 1024)


def _iter_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for p in root.rglob("*"):
        try:
            if p.is_file():
                paths.append(p)
        except OSError:
            continue
    paths.sort(key=lambda p: p.as_posix())
    return paths


def _archive_existing(path: Path) -> Path | None:
    if not path.exists():
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archived = path.with_name(f"{path.name}.bak.{ts}")
    try:
        archived.parent.mkdir(parents=True, exist_ok=True)
        path.rename(archived)
        return archived
    except Exception:
        # Best-effort fallback to copy-then-leave original in place.
        try:
            shutil.copy2(path, archived)
            return archived
        except Exception:
            return None


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except Exception:
                pass
        tmp_path.replace(path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


@dataclass(frozen=True)
class BackupEntry:
    kind: str  # repo|config|data
    relpath: str
    zip_path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class BackupManifest:
    schema_version: int
    created_utc: str
    entries: list[BackupEntry]
    includes_data: bool
    includes_keyring_bundle: bool


def _categorize_path(path: Path, *, repo: Path, config_dir: Path, data_dir: Path) -> tuple[str, str] | None:
    path = path.resolve()
    for kind, root in (("repo", repo), ("config", config_dir), ("data", data_dir)):
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        return kind, rel
    return None


def create_backup_bundle(
    *,
    output_path: str | Path,
    config_dir: str | Path,
    data_dir: str | Path,
    repo: str | Path | None = None,
    include_data: bool = False,
    include_keyring_bundle: bool = True,
    keyring_bundle_passphrase: str | None = None,
    keyring_backend: str = "auto",
    keyring_credential_name: str = "autocapture.keyring",
    require_key_protection: bool = False,
    keyring_path: str | Path | None = None,
    legacy_root_key_path: str | Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    out = Path(output_path)
    if out.exists() and not overwrite:
        return {"ok": False, "error": "output_exists", "path": str(out)}
    out.parent.mkdir(parents=True, exist_ok=True)

    repo_path = Path(repo).resolve() if repo else repo_root()
    cfg_root = Path(config_dir).resolve()
    data_root = Path(data_dir).resolve()

    config_user = cfg_root / "user.json"

    # Always include: user config, lockfile (repo/config/plugin_locks.json), anchors, ledger/journal.
    lockfile = repo_path / "config" / "plugin_locks.json"
    anchor_path = None
    # Anchor path may live under repo root (default) or elsewhere.
    try:
        default_anchor = repo_path / "data_anchor" / "anchors.ndjson"
        if default_anchor.exists():
            anchor_path = default_anchor
    except Exception:
        anchor_path = None
    ledger_path = data_root / "ledger.ndjson"
    journal_path = data_root / "journal.ndjson"

    must_exist: list[Path] = [config_user, lockfile]
    optional: list[Path] = []
    if anchor_path:
        optional.append(anchor_path)
    if ledger_path.exists():
        optional.append(ledger_path)
    if journal_path.exists():
        optional.append(journal_path)

    # Include the whole data dir only when asked; otherwise only critical NDJSON + DB pointers.
    data_files: list[Path] = []
    if include_data:
        data_files = _iter_files(data_root)
    else:
        # Minimal set: the NDJSON provenance chain plus metadata/state DBs if present.
        candidates = [
            ledger_path,
            journal_path,
            data_root / "metadata.db",
            data_root / "lexical.db",
            data_root / "vector.db",
            data_root / "audit" / "kernel_audit.db",
            data_root / "state" / "state_tape.db",
            data_root / "state" / "state_vector.db",
        ]
        for cand in candidates:
            if cand.exists() and cand.is_file():
                data_files.append(cand)

    files = []
    for p in must_exist:
        if not p.exists():
            return {"ok": False, "error": "missing_required_path", "path": str(p)}
        files.append(p)
    for p in optional:
        if p.exists() and p.is_file():
            files.append(p)
    for p in data_files:
        if p.exists() and p.is_file():
            files.append(p)
    # Stable unique by absolute path.
    uniq: dict[str, Path] = {}
    for p in files:
        try:
            uniq[str(p.resolve())] = p
        except Exception:
            uniq[str(p)] = p
    files = [uniq[k] for k in sorted(uniq)]

    entries: list[BackupEntry] = []

    with tempfile.TemporaryDirectory(prefix="autocapture_backup_") as tmp:
        tmp_root = Path(tmp)
        bundle_bytes: bytes | None = None
        if include_keyring_bundle:
            if not keyring_bundle_passphrase:
                return {"ok": False, "error": "missing_keyring_bundle_passphrase"}
            bundle_path = tmp_root / "keyring.bundle.json"
            ring = KeyRing.load(
                str(keyring_path) if keyring_path else str(data_root / "vault" / "keyring.json"),
                legacy_root_path=str(legacy_root_key_path) if legacy_root_key_path else str(data_root / "vault" / "root.key"),
                require_protection=bool(require_key_protection),
                backend=str(keyring_backend or "auto"),
                credential_name=str(keyring_credential_name or "autocapture.keyring"),
            )
            export_keyring_bundle(ring, path=str(bundle_path), passphrase=str(keyring_bundle_passphrase))
            bundle_bytes = bundle_path.read_bytes()

        with ZipFile(out, "w", compression=ZIP_DEFLATED) as zf:
            for path in files:
                cat = _categorize_path(path, repo=repo_path, config_dir=cfg_root, data_dir=data_root)
                if cat is None:
                    # Skip external paths: backup should remain portable/deterministic.
                    continue
                kind, rel = cat
                zip_path = f"{kind}/{rel}"
                sha = _sha256_path(path)
                size = int(path.stat().st_size)
                _zip_write_file(zf, zip_path, path)
                entries.append(
                    BackupEntry(
                        kind=kind,
                        relpath=rel,
                        zip_path=zip_path,
                        sha256=sha,
                        size_bytes=size,
                    )
                )

            if bundle_bytes is not None:
                sha = _sha256_bytes(bundle_bytes)
                _zip_write_bytes(zf, "data/vault/keyring.bundle.json", bundle_bytes)
                entries.append(
                    BackupEntry(
                        kind="data",
                        relpath="vault/keyring.bundle.json",
                        zip_path="data/vault/keyring.bundle.json",
                        sha256=sha,
                        size_bytes=len(bundle_bytes),
                    )
                )

            manifest = BackupManifest(
                schema_version=1,
                created_utc=_utc_now(),
                entries=sorted(entries, key=lambda e: (e.kind, e.relpath)),
                includes_data=bool(include_data),
                includes_keyring_bundle=bool(bundle_bytes is not None),
            )
            _zip_write_bytes(zf, "bundle_manifest.json", json.dumps(asdict(manifest), indent=2, sort_keys=True).encode("utf-8"))

    return {
        "ok": True,
        "path": str(out),
        "entries": len(entries),
        "includes_data": bool(include_data),
        "includes_keyring_bundle": bool(include_keyring_bundle),
    }


def restore_backup_bundle(
    *,
    bundle_path: str | Path,
    config_dir: str | Path,
    data_dir: str | Path,
    repo: str | Path | None = None,
    keyring_bundle_passphrase: str | None = None,
    restore_keyring_bundle: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    src = Path(bundle_path)
    if not src.exists():
        return {"ok": False, "error": "bundle_missing", "path": str(src)}
    repo_path = Path(repo).resolve() if repo else repo_root()
    cfg_root = Path(config_dir).resolve()
    data_root = Path(data_dir).resolve()

    extracted = 0
    archived: list[str] = []
    errors: list[str] = []

    with ZipFile(src, "r") as zf:
        try:
            manifest_raw = zf.read("bundle_manifest.json")
            manifest_obj = json.loads(manifest_raw.decode("utf-8"))
        except Exception as exc:
            return {"ok": False, "error": f"manifest_invalid:{exc}"}
        entries_raw = manifest_obj.get("entries", [])
        if not isinstance(entries_raw, list):
            return {"ok": False, "error": "manifest_entries_invalid"}

        # Verify hashes before any writes.
        for ent in entries_raw:
            if not isinstance(ent, dict):
                continue
            zip_path = str(ent.get("zip_path") or "")
            sha_expect = str(ent.get("sha256") or "")
            if not zip_path or not sha_expect:
                continue
            try:
                data = zf.read(zip_path)
            except Exception as exc:
                errors.append(f"missing_entry:{zip_path}:{exc}")
                continue
            if _sha256_bytes(data) != sha_expect:
                errors.append(f"sha256_mismatch:{zip_path}")
        if errors:
            return {"ok": False, "error": "integrity_check_failed", "issues": errors}

        for ent in entries_raw:
            if not isinstance(ent, dict):
                continue
            kind = str(ent.get("kind") or "")
            rel = str(ent.get("relpath") or "")
            zip_path = str(ent.get("zip_path") or "")
            if not kind or not rel or not zip_path:
                continue

            # Keyring bundle is handled separately (import into configured location).
            if zip_path == "data/vault/keyring.bundle.json":
                continue

            if kind == "repo":
                dest = repo_path / rel
            elif kind == "config":
                dest = cfg_root / rel
            elif kind == "data":
                dest = data_root / rel
            else:
                continue

            if dest.exists() and not overwrite:
                archived_path = _archive_existing(dest)
                if archived_path is not None:
                    archived.append(str(archived_path))
                else:
                    return {"ok": False, "error": "cannot_archive_existing", "path": str(dest)}

            dest.parent.mkdir(parents=True, exist_ok=True)
            data = zf.read(zip_path)
            if dest.suffix in {".json", ".ndjson", ".txt", ".md"}:
                atomic_write_text(dest, data.decode("utf-8", errors="strict"), fsync=True)
            else:
                _atomic_write_bytes(dest, data)
            extracted += 1

        if restore_keyring_bundle and any(
            isinstance(ent, dict) and str(ent.get("zip_path") or "") == "data/vault/keyring.bundle.json" for ent in entries_raw
        ):
            if not keyring_bundle_passphrase:
                return {"ok": False, "error": "missing_keyring_bundle_passphrase"}
            with tempfile.TemporaryDirectory(prefix="autocapture_restore_") as tmp:
                tmp_root = Path(tmp)
                bundle_out = tmp_root / "keyring.bundle.json"
                bundle_out.write_bytes(zf.read("data/vault/keyring.bundle.json"))
                # Import into the target data_dir vault path (archive existing; no deletion).
                dest_keyring = data_root / "vault" / "keyring.json"
                if dest_keyring.exists() and not overwrite:
                    archived_path = _archive_existing(dest_keyring)
                    if archived_path is not None:
                        archived.append(str(archived_path))
                    else:
                        return {"ok": False, "error": "cannot_archive_existing", "path": str(dest_keyring)}
                import_keyring_bundle(
                    path=str(bundle_out),
                    passphrase=str(keyring_bundle_passphrase),
                    keyring_path=str(dest_keyring),
                    require_protection=bool(os.name == "nt"),
                    backend="auto",
                    credential_name="autocapture.keyring",
                )

    return {"ok": True, "extracted": extracted, "archived": archived}
