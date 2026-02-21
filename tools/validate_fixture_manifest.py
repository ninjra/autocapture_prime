"""Validate fixture manifest schema and file paths."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from autocapture_nx.kernel.paths import resolve_repo_path


def _err(msg: str) -> None:
    print(f"ERROR: {msg}")


def _resolve_path(raw: str) -> Path:
    raw = str(raw or "").strip()
    if not raw:
        return Path()
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    # Handle Windows absolute paths when running in WSL/python on *nix.
    if ":" in raw[:3]:
        return Path(raw)
    return resolve_repo_path(candidate)


def validate_manifest(payload: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["manifest_root_not_object"]

    fixture_id = payload.get("fixture_id")
    if not fixture_id or not isinstance(fixture_id, str):
        errors.append("fixture_id_missing")
    version = payload.get("version")
    if version is None:
        errors.append("version_missing")

    inputs = payload.get("inputs")
    screenshots = None
    if isinstance(inputs, dict):
        screenshots = inputs.get("screenshots")
    if not isinstance(screenshots, list) or not screenshots:
        errors.append("inputs.screenshots_missing")
    else:
        for idx, item in enumerate(screenshots):
            if not isinstance(item, dict):
                errors.append(f"inputs.screenshots[{idx}]_not_object")
                continue
            path_val = item.get("path")
            if not path_val:
                errors.append(f"inputs.screenshots[{idx}].path_missing")
                continue
            resolved = _resolve_path(str(path_val))
            if not resolved or not resolved.exists():
                errors.append(f"inputs.screenshots[{idx}].path_not_found:{path_val}")
            if not item.get("id"):
                errors.append(f"inputs.screenshots[{idx}].id_missing")

    queries = payload.get("queries", {})
    if not isinstance(queries, dict):
        errors.append("queries_not_object")
        return errors
    mode = str(queries.get("mode", "auto")).strip().lower()
    if mode not in {"auto", "explicit"}:
        errors.append("queries.mode_invalid")
    explicit = queries.get("explicit", [])
    if explicit is not None and not isinstance(explicit, list):
        errors.append("queries.explicit_not_list")
    auto_cfg = queries.get("auto", {})
    if auto_cfg is not None and not isinstance(auto_cfg, dict):
        errors.append("queries.auto_not_object")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    args = parser.parse_args(argv)
    manifest_path = _resolve_path(args.path)
    if not manifest_path.exists():
        _err(f"manifest not found: {args.path}")
        return 1
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _err(f"manifest read failed: {exc}")
        return 1
    errors = validate_manifest(payload)
    if errors:
        for err in errors:
            _err(err)
        return 1
    print("OK: fixture manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
