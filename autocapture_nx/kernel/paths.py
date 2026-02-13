"""Path resolution helpers that avoid CWD dependence."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import importlib.resources as resources

try:  # platformdirs may not be installed in minimal dev environments
    from platformdirs import PlatformDirs
except Exception:  # pragma: no cover - fallback path is exercised in tests
    PlatformDirs = None  # type: ignore[assignment]


_ROOT_ENV = "AUTOCAPTURE_ROOT"
_CONFIG_ENV = "AUTOCAPTURE_CONFIG_DIR"
_DATA_ENV = "AUTOCAPTURE_DATA_DIR"
_APP_NAME = "Autocapture"


def repo_root() -> Path:
    override = os.getenv(_ROOT_ENV)
    if override:
        return Path(override).expanduser().absolute()
    start = Path(__file__).absolute().parent
    for parent in [start, *start.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
        if (parent / "config").is_dir() and (parent / "contracts").is_dir():
            return parent
    return start.parents[2]


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return repo_root() / candidate


def config_dir() -> Path:
    return resolve_repo_path("config")


def contracts_dir() -> Path:
    return resolve_repo_path("contracts")


def plugins_dir() -> Path:
    return resolve_repo_path("plugins")


def data_dir(default_rel: str = "data") -> Path:
    return resolve_repo_path(default_rel)


def _fallback_config_dir() -> Path:
    home = Path.home()
    if os.name == "nt":
        base = os.getenv("APPDATA")
        if base:
            return Path(base) / _APP_NAME
        return home / "AppData" / "Roaming" / _APP_NAME
    base = os.getenv("XDG_CONFIG_HOME")
    if base:
        return Path(base) / _APP_NAME
    return home / ".config" / _APP_NAME


def _fallback_data_dir() -> Path:
    home = Path.home()
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA")
        if base:
            return Path(base) / _APP_NAME
        return home / "AppData" / "Local" / _APP_NAME
    base = os.getenv("XDG_DATA_HOME")
    if base:
        return Path(base) / _APP_NAME
    return home / ".local" / "share" / _APP_NAME


def default_config_dir() -> Path:
    override = os.getenv(_CONFIG_ENV)
    if override:
        return _resolve_dir(override)
    if PlatformDirs is None:
        return _fallback_config_dir()
    return Path(PlatformDirs(_APP_NAME, appauthor=False).user_config_dir)


def default_data_dir() -> Path:
    override = os.getenv(_DATA_ENV)
    if override:
        return _resolve_dir(override)
    if PlatformDirs is None:
        candidate = _fallback_data_dir()
    else:
        candidate = Path(PlatformDirs(_APP_NAME, appauthor=False).user_data_dir)
    if _is_writable_dir(candidate):
        return candidate
    fallback = repo_root() / "data"
    if _is_writable_dir(fallback):
        return fallback
    return candidate


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False
    return os.access(path, os.W_OK)


def _resource_text_from(pkg: str, rel_path: str) -> str | None:
    try:
        target = resources.files(pkg).joinpath(rel_path)
    except Exception:
        return None
    if target.is_file():
        return target.read_text(encoding="utf-8")
    return None


def _resource_text(rel_path: str) -> str | None:
    prefix_map = {
        "config/": "config",
        "contracts/": "contracts",
        "plugins/": "plugins",
    }
    for prefix, pkg in prefix_map.items():
        if rel_path.startswith(prefix):
            subpath = rel_path[len(prefix):]
            text = _resource_text_from(pkg, subpath)
            if text is not None:
                return text
    text = _resource_text_from("autocapture_nx", rel_path)
    if text is not None:
        return text
    return None


def _relative_to_root(path: Path) -> str | None:
    if not path.is_absolute():
        return path.as_posix()
    root = repo_root()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


def load_text(path: str | Path) -> str:
    resolved = resolve_repo_path(path)
    if resolved.exists():
        return resolved.read_text(encoding="utf-8")
    rel = _relative_to_root(resolved)
    if rel:
        text = _resource_text(rel)
        if text is not None:
            return text
    raise FileNotFoundError(f"Missing resource: {resolved}")


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(load_text(path))


def _resolve_path(value: str) -> str:
    if not value:
        return value
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str(resolve_repo_path(path))


def _resolve_dir(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return resolve_repo_path(path)


def apply_path_defaults(
    config: dict[str, Any],
    user_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updated = deepcopy(config)
    paths = updated.get("paths")
    if not isinstance(paths, dict):
        paths = {}

    user_paths: dict[str, Any] = {}
    user_storage: dict[str, Any] = {}
    if isinstance(user_overrides, dict):
        if isinstance(user_overrides.get("paths"), dict):
            user_paths = user_overrides.get("paths", {})
        if isinstance(user_overrides.get("storage"), dict):
            user_storage = user_overrides.get("storage", {})

    config_dir_value = (
        user_paths.get("config_dir")
        or os.getenv(_CONFIG_ENV)
        or paths.get("config_dir")
        or str(default_config_dir())
    )
    preferred_windows = ""
    if isinstance(user_paths, dict) and user_paths.get("preferred_data_dir_windows"):
        preferred_windows = str(user_paths.get("preferred_data_dir_windows") or "")
    elif isinstance(paths, dict) and paths.get("preferred_data_dir_windows"):
        preferred_windows = str(paths.get("preferred_data_dir_windows") or "")
    preferred_windows = preferred_windows.strip()
    data_dir_value = (
        user_paths.get("data_dir")
        or os.getenv(_DATA_ENV)
        or user_storage.get("data_dir")
        or paths.get("data_dir")
    )
    if not data_dir_value:
        if os.name == "nt" and preferred_windows:
            data_dir_value = preferred_windows
        else:
            data_dir_value = str(default_data_dir())

    config_dir_abs = _resolve_dir(str(config_dir_value))
    data_dir_abs = _resolve_dir(str(data_dir_value))

    paths["config_dir"] = str(config_dir_abs)
    paths["data_dir"] = str(data_dir_abs)
    updated["paths"] = paths

    storage = updated.get("storage")
    if not isinstance(storage, dict):
        storage = {}
    storage["data_dir"] = str(data_dir_abs)
    updated["storage"] = storage

    return updated


def normalize_config_paths(
    config: dict[str, Any],
    legacy_data_dir: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    updated = deepcopy(config)
    paths_cfg = updated.get("paths")
    if not isinstance(paths_cfg, dict):
        paths_cfg = {}
        updated["paths"] = paths_cfg

    config_dir_value = paths_cfg.get("config_dir") or str(default_config_dir())
    data_dir_value = paths_cfg.get("data_dir") or str(default_data_dir())
    config_dir_abs = _resolve_dir(str(config_dir_value))
    data_dir_abs = _resolve_dir(str(data_dir_value))
    paths_cfg["config_dir"] = str(config_dir_abs)
    paths_cfg["data_dir"] = str(data_dir_abs)

    legacy_prefixes: list[str] = []
    candidates: list[str] = []
    if isinstance(legacy_data_dir, (list, tuple)):
        candidates = [c for c in legacy_data_dir if isinstance(c, str)]
    elif isinstance(legacy_data_dir, str):
        candidates = [legacy_data_dir]
    for candidate in candidates:
        legacy_path = Path(candidate)
        if legacy_path.is_absolute():
            continue
        prefix = legacy_path.as_posix().rstrip("/")
        if prefix and prefix not in legacy_prefixes:
            legacy_prefixes.append(prefix)

    storage = updated.get("storage", {})
    if not isinstance(storage, dict):
        storage = {}
        updated["storage"] = storage
    storage["data_dir"] = str(data_dir_abs)

    def _normalize_storage_value(value: str) -> str:
        path = Path(value)
        if path.is_absolute():
            return str(path)
        text = value.replace("\\", "/")
        for prefix in legacy_prefixes:
            if text.startswith(f"{prefix}/"):
                text = text[len(prefix) + 1 :]
                break
        return str((data_dir_abs / text).resolve())

    for key in (
        "spool_dir",
        "media_dir",
        "blob_dir",
        "lexical_path",
        "vector_path",
        "metadata_path",
        "audit_db_path",
        # State layer SQLite paths must follow data_dir overrides (e.g. temp dirs in tests).
        "state_tape_path",
        "state_vector_path",
    ):
        if key in storage and isinstance(storage[key], str):
            storage[key] = _normalize_storage_value(storage[key])
    anchor = storage.get("anchor", {})
    if isinstance(anchor, dict) and "path" in anchor and isinstance(anchor.get("path"), str):
        # Anchor logs must remain run-scoped (follow data_dir overrides) but must
        # not live *inside* data_dir. Keeping anchors outside data_dir provides a
        # clearer integrity boundary and is enforced by doctor checks.
        anchor_path = str(anchor.get("path") or "")
        anchor_path_obj = Path(anchor_path)
        if anchor_path_obj.is_absolute():
            anchor["path"] = str(anchor_path_obj)
        else:
            # Resolve relative to the parent of data_dir so each run gets its own
            # anchor domain even when tests override data_dir to a temp dir.
            text = anchor_path.replace("\\", "/")
            for prefix in legacy_prefixes:
                if text.startswith(f"{prefix}/"):
                    text = text[len(prefix) + 1 :]
                    break
            anchor["path"] = str((data_dir_abs.parent / text).resolve())
    crypto = storage.get("crypto", {})
    if isinstance(crypto, dict):
        for key in ("root_key_path", "keyring_path"):
            if key in crypto and isinstance(crypto[key], str):
                crypto[key] = _normalize_storage_value(crypto[key])

    indexing = updated.get("indexing", {})
    qdrant = indexing.get("qdrant", {})
    if isinstance(qdrant, dict) and "binary_path" in qdrant and isinstance(qdrant.get("binary_path"), str):
        qdrant["binary_path"] = _resolve_path(qdrant["binary_path"])

    devtools = updated.get("devtools", {})
    ast_ir = devtools.get("ast_ir", {})
    if isinstance(ast_ir, dict) and "pin_path" in ast_ir and isinstance(ast_ir.get("pin_path"), str):
        ast_ir["pin_path"] = _resolve_path(ast_ir["pin_path"])

    plugins = updated.get("plugins", {})
    locks = plugins.get("locks", {})
    if isinstance(locks, dict) and "lockfile" in locks and isinstance(locks.get("lockfile"), str):
        locks["lockfile"] = _resolve_path(locks["lockfile"])
    search_paths = plugins.get("search_paths", [])
    if isinstance(search_paths, list):
        plugins["search_paths"] = [
            _resolve_path(path) if isinstance(path, str) else path for path in search_paths
        ]

    return updated
