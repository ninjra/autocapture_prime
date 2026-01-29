"""Screenshot capture helpers (dedupe + hashing + PNG encoding)."""

from __future__ import annotations

import hashlib
import time
from typing import Any
from dataclasses import dataclass


def hash_bytes(data: bytes, *, algo: str = "blake2b", sample_bytes: int = 0) -> str:
    if sample_bytes > 0 and len(data) > sample_bytes:
        data = data[:sample_bytes]
    algo = str(algo or "blake2b").lower()
    digest: Any
    if algo == "sha256":
        digest = hashlib.sha256()
    else:
        digest = hashlib.blake2b(digest_size=32)
    digest.update(data)
    return digest.hexdigest()


def encode_png(image, *, compress_level: int = 3) -> bytes:
    from io import BytesIO

    level = int(compress_level)
    if level < 0:
        level = 0
    if level > 9:
        level = 9
    buffer = BytesIO()
    image.save(buffer, format="PNG", compress_level=level, optimize=False)
    return buffer.getvalue()


@dataclass
class ScreenshotDeduper:
    enabled: bool = True
    hash_algo: str = "blake2b"
    sample_bytes: int = 0
    force_interval_s: float = 0.0
    _last_hash: str | None = None
    _last_saved_at: float | None = None

    def fingerprint(self, data: bytes) -> str:
        return hash_bytes(data, algo=self.hash_algo, sample_bytes=self.sample_bytes)

    def should_store(self, fingerprint: str, *, now: float | None = None) -> tuple[bool, bool]:
        if not self.enabled:
            return True, False
        if now is None:
            now = time.monotonic()
        if self._last_hash is None:
            return True, False
        if self._last_hash != fingerprint:
            return True, False
        if self.force_interval_s > 0 and self._last_saved_at is not None:
            if now - self._last_saved_at >= self.force_interval_s:
                return True, True
        return False, True

    def mark_saved(self, fingerprint: str, *, now: float | None = None) -> None:
        if now is None:
            now = time.monotonic()
        self._last_hash = fingerprint
        self._last_saved_at = now
