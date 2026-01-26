"""Validator implementations for Codex."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from autocapture.codex.report import RequirementReport, ValidatorReport
from autocapture.codex.spec import RequirementSpec, ValidatorSpec


@dataclass(frozen=True)
class ValidationContext:
    project_root: Path


def _resolve_command(command: Iterable[str]) -> list[str]:
    cmd = list(command)
    if not cmd:
        return cmd
    if cmd[0] == "autocapture":
        return [sys.executable, "-m", "autocapture_nx", *cmd[1:]]
    return cmd


def _run_command(command: Iterable[str]) -> subprocess.CompletedProcess:
    cmd = _resolve_command(command)
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    return subprocess.run(cmd, env=env, capture_output=True, text=True)


def _validator_python_import(spec: ValidatorSpec) -> ValidatorReport:
    target = spec.config.get("target", "")
    if ":" not in target:
        return ValidatorReport(type=spec.type, ok=False, detail="invalid_target", data={"target": target})
    module_name, attr_name = target.split(":", 1)
    try:
        module = __import__(module_name, fromlist=[attr_name])
        getattr(module, attr_name)
        return ValidatorReport(type=spec.type, ok=True, detail="ok", data={"target": target})
    except Exception as exc:  # pragma: no cover - error path
        return ValidatorReport(type=spec.type, ok=False, detail=str(exc), data={"target": target})


def _validator_unit_test(spec: ValidatorSpec) -> ValidatorReport:
    target = spec.config.get("target", "")
    result = subprocess.run(
        [sys.executable, "-m", "unittest", target, "-q"],
        env={**os.environ, "PYTHONPATH": "."},
        capture_output=True,
        text=True,
    )
    ok = result.returncode == 0
    detail = "ok" if ok else (result.stdout + result.stderr).strip()
    return ValidatorReport(type=spec.type, ok=ok, detail=detail or "ok", data={"target": target})


def _is_self_codex_validate(command: Iterable[str]) -> bool:
    cmd = list(command)
    return len(cmd) >= 3 and cmd[0] == "autocapture" and cmd[1] == "codex" and cmd[2] == "validate"


def _validator_cli_exit(spec: ValidatorSpec) -> ValidatorReport:
    command = spec.config.get("command", [])
    if _is_self_codex_validate(command) and os.getenv("AUTOCAPTURE_CODEX_SKIP_SELF_VALIDATE") == "1":
        return ValidatorReport(type=spec.type, ok=True, detail="self_skip", data={"command": list(command)})
    expected = int(spec.config.get("expected_exit_code", 0))
    result = _run_command(command)
    ok = result.returncode == expected
    detail = "ok" if ok else f"exit={result.returncode}"
    return ValidatorReport(type=spec.type, ok=ok, detail=detail, data={"command": list(command)})


def _validator_cli_output_regex_absent(spec: ValidatorSpec) -> ValidatorReport:
    command = spec.config.get("command", [])
    patterns = spec.config.get("patterns", [])
    result = _run_command(command)
    haystack = (result.stdout or "") + "\n" + (result.stderr or "")
    violations = [pat for pat in patterns if re.search(pat, haystack)]
    ok = len(violations) == 0
    detail = "ok" if ok else f"patterns_present:{violations}"
    return ValidatorReport(type=spec.type, ok=ok, detail=detail, data={"command": list(command), "violations": violations})


def _validator_cli_json(spec: ValidatorSpec) -> ValidatorReport:
    command = spec.config.get("command", [])
    must_keys = spec.config.get("must_contain_json_keys", [])
    result = _run_command(command)
    if result.returncode != 0:
        return ValidatorReport(type=spec.type, ok=False, detail=f"exit={result.returncode}", data={"stdout": result.stdout, "stderr": result.stderr})
    try:
        payload = json.loads(result.stdout)
    except Exception as exc:
        return ValidatorReport(type=spec.type, ok=False, detail=f"json_parse_failed:{exc}", data={"stdout": result.stdout})
    missing = [k for k in must_keys if k not in payload]
    ok = len(missing) == 0
    detail = "ok" if ok else f"missing_keys:{missing}"
    return ValidatorReport(type=spec.type, ok=ok, detail=detail, data={"missing": missing})


def _load_fastapi_app():
    from fastapi import FastAPI
    import importlib

    module = importlib.import_module("autocapture.web.api")
    if hasattr(module, "app"):
        app = getattr(module, "app")
        if isinstance(app, FastAPI):
            return app
    if hasattr(module, "get_app"):
        app = module.get_app()  # type: ignore[attr-defined]
        if isinstance(app, FastAPI):
            return app
    raise RuntimeError("FastAPI app not found in autocapture.web.api")


def _validator_http_routes_absent(spec: ValidatorSpec) -> ValidatorReport:
    paths = spec.config.get("must_not_include_paths", [])
    try:
        app = _load_fastapi_app()
    except Exception as exc:
        return ValidatorReport(type=spec.type, ok=False, detail=str(exc), data={"paths": paths})
    existing = {route.path for route in app.routes if hasattr(route, "path")}
    violations = [p for p in paths if p in existing]
    ok = len(violations) == 0
    detail = "ok" if ok else f"routes_present:{violations}"
    return ValidatorReport(type=spec.type, ok=ok, detail=detail, data={"violations": violations})


def _validator_http_endpoint(spec: ValidatorSpec) -> ValidatorReport:
    method = str(spec.config.get("method", "GET")).upper()
    path = spec.config.get("path", "/")
    expects = spec.config.get("expects_json_keys", [])
    try:
        app = _load_fastapi_app()
        from fastapi.testclient import TestClient
        client = TestClient(app)
        if method == "GET":
            response = client.get(path)
        elif method == "POST":
            response = client.post(path, json={"query": "test"})
        else:
            return ValidatorReport(type=spec.type, ok=False, detail=f"unsupported_method:{method}", data={"path": path})
        if response.status_code >= 400:
            return ValidatorReport(type=spec.type, ok=False, detail=f"status={response.status_code}", data={"body": response.text})
        data = response.json()
        missing = [k for k in expects if k not in data]
        ok = len(missing) == 0
        detail = "ok" if ok else f"missing_keys:{missing}"
        return ValidatorReport(type=spec.type, ok=ok, detail=detail, data={"missing": missing})
    except Exception as exc:
        return ValidatorReport(type=spec.type, ok=False, detail=str(exc), data={"path": path})


def _iter_plugin_manifests(root: Path) -> list[Path]:
    if not root.exists():
        return []
    paths: list[Path] = []
    for ext in (".yaml", ".yml", ".json"):
        paths.extend(sorted(root.rglob(f"*{ext}")))
    return paths


def _validator_plugins_have_ids(spec: ValidatorSpec) -> ValidatorReport:
    required = set(spec.config.get("required_plugin_ids", []))
    from autocapture.plugins.manifest import PluginManifest

    manifests = _iter_plugin_manifests(Path("autocapture_plugins"))
    found: set[str] = set()
    for manifest in manifests:
        data = PluginManifest.from_path(manifest)
        found.add(data.plugin_id)
    missing = sorted(required - found)
    ok = len(missing) == 0
    detail = "ok" if ok else f"missing:{missing}"
    return ValidatorReport(type=spec.type, ok=ok, detail=detail, data={"missing": missing})


def _validator_plugins_have_kinds(spec: ValidatorSpec) -> ValidatorReport:
    required = set(spec.config.get("required_kinds", []))
    from autocapture.plugins.manifest import PluginManifest

    manifests = _iter_plugin_manifests(Path("autocapture_plugins"))
    kinds: set[str] = set()
    for manifest in manifests:
        data = PluginManifest.from_path(manifest)
        for entry in data.extensions:
            kind = entry.kind
            if kind:
                kinds.add(kind)
    missing = sorted(required - kinds)
    ok = len(missing) == 0
    detail = "ok" if ok else f"missing:{missing}"
    return ValidatorReport(type=spec.type, ok=ok, detail=detail, data={"missing": missing})


def _run_validator(spec: ValidatorSpec) -> ValidatorReport:
    if spec.type == "python_import":
        return _validator_python_import(spec)
    if spec.type == "unit_test":
        return _validator_unit_test(spec)
    if spec.type == "cli_exit":
        return _validator_cli_exit(spec)
    if spec.type == "cli_output_regex_absent":
        return _validator_cli_output_regex_absent(spec)
    if spec.type == "cli_json":
        return _validator_cli_json(spec)
    if spec.type == "http_routes_absent":
        return _validator_http_routes_absent(spec)
    if spec.type == "http_endpoint":
        return _validator_http_endpoint(spec)
    if spec.type == "plugins_have_ids":
        return _validator_plugins_have_ids(spec)
    if spec.type == "plugins_have_kinds":
        return _validator_plugins_have_kinds(spec)
    return ValidatorReport(type=spec.type, ok=False, detail="unknown_validator", data={})


def validate_requirement(req: RequirementSpec) -> RequirementReport:
    missing = [path for path in req.artifacts if not Path(path).exists()]
    validators = [_run_validator(v) for v in req.validators]
    return RequirementReport(
        req_id=req.req_id,
        title=req.title,
        pillars=req.pillars,
        artifacts_ok=len(missing) == 0,
        artifacts_missing=missing,
        validators=validators,
    )
