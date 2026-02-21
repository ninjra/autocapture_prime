"""Archive export/import for MX."""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
import stat


@dataclass
class ArchiveManifest:
    files: dict[str, str]


def _hash_bytes(data: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(data)
    return digest.hexdigest()


def _zipinfo(name: str, *, compression: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.date_time = (1980, 1, 1, 0, 0, 0)
    info.compress_type = compression
    info.external_attr = 0o644 << 16
    return info


def _is_safe_member(name: str) -> bool:
    raw = str(name or "")
    if not raw:
        return False
    normalized = raw.replace("\\", "/")
    if normalized.startswith("/"):
        return False
    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    if ":" in parts[0]:
        # Reject Windows drive-prefixed absolute paths.
        return False
    return True


def _is_symlink_member(info: zipfile.ZipInfo) -> bool:
    mode = (int(info.external_attr) >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _safe_extractall(zf: zipfile.ZipFile, target_dir: Path) -> None:
    target = Path(target_dir).resolve()
    members = list(zf.infolist())
    for info in members:
        if not _is_safe_member(info.filename):
            raise ValueError(f"unsafe_zip_member:{info.filename}")
        if _is_symlink_member(info):
            raise ValueError(f"unsafe_zip_symlink:{info.filename}")
        out_path = (target / info.filename).resolve()
        if out_path != target and target not in out_path.parents:
            raise ValueError(f"zip_slip:{info.filename}")
    for info in members:
        out_path = (target / info.filename).resolve()
        if info.is_dir():
            out_path.mkdir(parents=True, exist_ok=True)
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info, "r") as src, out_path.open("wb") as dst:
            dst.write(src.read())


def create_archive(source_dir: str | Path, output_path: str | Path) -> Path:
    source_dir = Path(source_dir)
    output_path = Path(output_path)
    files: dict[str, str] = {}
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(source_dir).as_posix()
            data = path.read_bytes()
            files[rel] = _hash_bytes(data)
            zf.writestr(_zipinfo(rel, compression=zipfile.ZIP_DEFLATED), data)
        manifest = {"schema_version": 1, "files": files}
        zf.writestr(
            _zipinfo("manifest.json", compression=zipfile.ZIP_DEFLATED),
            json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
        )
    return output_path


def verify_archive(path: str | Path) -> tuple[bool, list[str]]:
    path = Path(path)
    issues: list[str] = []
    with zipfile.ZipFile(path, "r") as zf:
        try:
            manifest = json.loads(zf.read("manifest.json"))
        except Exception:
            return False, ["manifest_missing"]
        files = manifest.get("files", {})
        for rel, expected in files.items():
            if not _is_safe_member(str(rel)):
                issues.append(f"unsafe_member:{rel}")
                continue
            try:
                data = zf.read(rel)
            except KeyError:
                issues.append(f"missing_member:{rel}")
                continue
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected:
                issues.append(f"hash_mismatch:{rel}")
    return len(issues) == 0, issues


class Exporter:
    def __init__(self, source_dir: Path) -> None:
        self.source_dir = source_dir

    def export(self, output_path: str | Path) -> Path:
        return create_archive(self.source_dir, output_path)


class Importer:
    def __init__(self, target_dir: Path, *, safe_extract: bool = True) -> None:
        self.target_dir = target_dir
        self.safe_extract = bool(safe_extract)

    def import_archive(self, archive_path: str | Path) -> Path:
        ok, issues = verify_archive(archive_path)
        if not ok:
            raise ValueError(f"archive verification failed: {issues}")
        with zipfile.ZipFile(archive_path, "r") as zf:
            if self.safe_extract:
                _safe_extractall(zf, self.target_dir)
            else:
                zf.extractall(self.target_dir)
        return self.target_dir


def create_exporter(plugin_id: str):
    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config

    config = load_config(default_config_paths(), safe_mode=False)
    data_dir = Path(config.get("storage", {}).get("data_dir", "data"))
    return Exporter(data_dir)


def create_importer(plugin_id: str):
    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config

    config = load_config(default_config_paths(), safe_mode=False)
    data_dir = Path(config.get("storage", {}).get("data_dir", "data"))
    safe_extract = bool(config.get("storage", {}).get("archive", {}).get("safe_extract", True))
    return Importer(data_dir, safe_extract=safe_extract)


def create_compressor(plugin_id: str):
    return Exporter(Path("."))
