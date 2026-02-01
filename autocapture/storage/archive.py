"""Archive export/import for MX."""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path


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
            data = zf.read(rel)
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
    def __init__(self, target_dir: Path) -> None:
        self.target_dir = target_dir

    def import_archive(self, archive_path: str | Path) -> Path:
        ok, issues = verify_archive(archive_path)
        if not ok:
            raise ValueError(f"archive verification failed: {issues}")
        with zipfile.ZipFile(archive_path, "r") as zf:
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
    return Importer(data_dir)


def create_compressor(plugin_id: str):
    return Exporter(Path("."))
