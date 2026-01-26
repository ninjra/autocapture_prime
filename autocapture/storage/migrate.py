"""Storage data directory migration helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from autocapture_nx.kernel.hashing import sha256_file


@dataclass
class MigrationResult:
    src: str
    dst: str
    files: int
    bytes: int
    verified: int
    dry_run: bool


def migrate_data_dir(src: str, dst: str, *, dry_run: bool = False, verify: bool = True) -> MigrationResult:
    src_path = Path(src)
    dst_path = Path(dst)
    if not src_path.exists():
        raise FileNotFoundError(f"Source data_dir missing: {src}")
    files = 0
    total_bytes = 0
    verified = 0
    for file_path in sorted([p for p in src_path.rglob("*") if p.is_file()]):
        rel = file_path.relative_to(src_path)
        dest_path = dst_path / rel
        files += 1
        total_bytes += file_path.stat().st_size
        if dry_run:
            continue
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, dest_path)
        if verify:
            if sha256_file(file_path) != sha256_file(dest_path):
                raise RuntimeError(f"Hash mismatch for {rel}")
            verified += 1
    return MigrationResult(
        src=str(src_path),
        dst=str(dst_path),
        files=files,
        bytes=total_bytes,
        verified=verified,
        dry_run=dry_run,
    )
