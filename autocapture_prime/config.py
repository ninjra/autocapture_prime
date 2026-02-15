from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PrimeConfig:
    raw: dict[str, Any]

    @property
    def spool_root(self) -> Path:
        return Path(self.raw.get("spool", {}).get("root_dir_linux", "/mnt/d/autocapture")).expanduser()

    @property
    def poll_interval_ms(self) -> int:
        value = int(self.raw.get("ingest", {}).get("poll_interval_ms", 1500))
        return max(100, value)

    @property
    def max_parallel_sessions(self) -> int:
        value = int(self.raw.get("ingest", {}).get("max_parallel_sessions", 2))
        return max(1, value)

    @property
    def storage_root(self) -> Path:
        return Path(self.raw.get("storage", {}).get("root_dir", "artifacts/chronicle")).expanduser()

    @property
    def vllm_base_url(self) -> str:
        return str(self.raw.get("vllm", {}).get("base_url", "http://127.0.0.1:8000"))

    @property
    def vllm_model(self) -> str:
        return str(self.raw.get("vllm", {}).get("model", "OpenGVLab/InternVL3_5-8B"))

    @property
    def api_host(self) -> str:
        return str(self.raw.get("chronicle_api", {}).get("host", "127.0.0.1"))

    @property
    def api_port(self) -> int:
        return int(self.raw.get("chronicle_api", {}).get("port", 7020))

    @property
    def top_k_frames(self) -> int:
        value = int(self.raw.get("qa", {}).get("top_k_frames", 4))
        return max(1, value)

    @property
    def allow_mm_embeds(self) -> bool:
        return bool(self.raw.get("privacy", {}).get("allow_mm_embeds", False))

    @property
    def ocr_engine(self) -> str:
        return str(self.raw.get("ocr", {}).get("engine", "paddleocr"))

    @property
    def ocr_full_frame_scale(self) -> float:
        value = float(self.raw.get("ocr", {}).get("full_frame_scale", 1.0))
        return max(0.1, min(1.0, value))

    @property
    def ocr_roi_strategy(self) -> str:
        return str(self.raw.get("ocr", {}).get("roi_strategy", "none")).strip().lower()

    @property
    def layout_engine(self) -> str:
        return str(self.raw.get("layout", {}).get("engine", "uied"))

    @property
    def ocr_cache_dir(self) -> Path:
        return Path(self.raw.get("ocr", {}).get("cache_dir", "artifacts/ocr_cache")).expanduser()

    @property
    def enable_duckdb(self) -> bool:
        return bool(self.raw.get("index", {}).get("enable_duckdb", True))

    @property
    def enable_faiss(self) -> bool:
        return bool(self.raw.get("index", {}).get("enable_faiss", False))

    @property
    def allow_agpl(self) -> bool:
        return bool(self.raw.get("layout", {}).get("allow_agpl", False))

    @property
    def trust_remote_code(self) -> bool:
        return bool(self.raw.get("vllm", {}).get("trust_remote_code", False))


def load_prime_config(path: str | Path | None = None) -> PrimeConfig:
    cfg_path = Path(path).expanduser() if path else Path("config/autocapture_prime.yaml")
    payload: dict[str, Any] = {}
    if cfg_path.exists():
        loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            payload = loaded
    return PrimeConfig(raw=payload)
