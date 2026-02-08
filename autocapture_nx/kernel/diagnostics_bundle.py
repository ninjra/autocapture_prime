"""Deterministic diagnostics bundle export (OPS-03).

This bundle is intended for support/debugging. It must:
- Be deterministic where feasible (stable ordering, fixed zip timestamps).
- Redact secrets at export boundaries (raw-first local store remains intact).
- Avoid deletion: archives/creates only.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.hashing import sha256_bytes, sha256_file


_ZIP_TS = (1980, 1, 1, 0, 0, 0)  # constant to keep zip deterministic across runs


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_config(config: dict[str, Any]) -> dict[str, Any]:
    cfg = json.loads(json.dumps(config)) if isinstance(config, dict) else {}
    gateway = cfg.get("gateway")
    if isinstance(gateway, dict):
        if "openai_api_key" in gateway and gateway.get("openai_api_key"):
            gateway["openai_api_key"] = "[REDACTED]"
    return cfg


def _redact_text(text: str) -> str:
    s = str(text or "")
    # Best-effort token redaction.
    for needle in ("Bearer ", "bearer "):
        if needle in s:
            parts = s.split(needle)
            out = [parts[0]]
            for tail in parts[1:]:
                # redact up to whitespace/newline
                i = 0
                while i < len(tail) and not tail[i].isspace():
                    i += 1
                out.append(needle + "[REDACTED]" + tail[i:])
            s = "".join(out)
    return s


def _tail_lines(path: Path, max_lines: int) -> str:
    if max_lines <= 0:
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return ""
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return "\n".join(lines) + ("\n" if lines else "")


@dataclass(frozen=True)
class DiagnosticsBundleResult:
    path: str
    bundle_sha256: str
    manifest: dict[str, Any]


def create_diagnostics_bundle(
    *,
    config: dict[str, Any],
    doctor_report: dict[str, Any],
    out_dir: str | Path | None = None,
    include_logs_tail_lines: int = 500,
) -> DiagnosticsBundleResult:
    storage = config.get("storage", {}) if isinstance(config, dict) else {}
    data_dir = Path(str(storage.get("data_dir", "data")))
    run_id = str(config.get("runtime", {}).get("run_id") or "run")

    if out_dir is None:
        out_dir = data_dir / "diagnostics" / "bundles"
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    ts = _utc_now_iso().replace(":", "").replace("-", "").replace(".", "")
    out_path = out_root / f"diagnostics_{run_id}_{ts}.zip"

    files: list[tuple[str, bytes]] = []

    # doctor report (already safe to export).
    files.append(("doctor_report.json", json.dumps(doctor_report, sort_keys=True, indent=2).encode("utf-8")))

    # config snapshot (sanitized export boundary).
    redacted_cfg = _redact_config(config)
    files.append(("config.snapshot.json", json.dumps(redacted_cfg, sort_keys=True, indent=2).encode("utf-8")))

    # effective config snapshot if present on disk.
    effective_path = data_dir / "config.effective.json"
    if effective_path.exists():
        try:
            files.append(("config.effective.json", effective_path.read_bytes()))
        except Exception:
            pass

    # plugin locks + contract lock for provenance debugging.
    lockfile = Path(str(config.get("plugins", {}).get("locks", {}).get("lockfile") or "config/plugin_locks.json"))
    if not lockfile.is_absolute():
        lockfile = (Path(__file__).resolve().parents[2] / lockfile).resolve()
    if lockfile.exists():
        try:
            files.append(("plugin_locks.json", lockfile.read_bytes()))
        except Exception:
            pass
    contract_lock = (Path(__file__).resolve().parents[2] / "contracts" / "lock.json").resolve()
    if contract_lock.exists():
        try:
            files.append(("contracts.lock.json", contract_lock.read_bytes()))
        except Exception:
            pass

    # recent logs (tail, redacted).
    logs_dir = data_dir / "logs"
    for name in ("core.jsonl", "web.jsonl", "plugin_host.jsonl"):
        p = logs_dir / name
        if not p.exists():
            continue
        content = _redact_text(_tail_lines(p, include_logs_tail_lines)).encode("utf-8")
        files.append((f"logs/{name}", content))

    # telemetry snapshot (in-process may be empty, but include for completeness).
    try:
        from autocapture_nx.kernel.telemetry import telemetry_snapshot

        files.append(("telemetry.json", json.dumps(telemetry_snapshot(), sort_keys=True, indent=2).encode("utf-8")))
    except Exception:
        pass

    # deterministic ordering
    files.sort(key=lambda item: item[0])

    # bundle manifest with sha256 of all included files.
    manifest_files: list[dict[str, Any]] = []
    for rel, content in files:
        manifest_files.append({"path": rel, "sha256": sha256_bytes(content), "bytes": int(len(content))})
    manifest = {
        "schema_version": 1,
        "generated_at_utc": _utc_now_iso(),
        "run_id": run_id,
        "files": manifest_files,
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8")
    files.insert(0, ("bundle_manifest.json", manifest_bytes))

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel, content in files:
            zi = zipfile.ZipInfo(rel)
            zi.date_time = _ZIP_TS
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, content)

    bundle_sha256 = sha256_file(out_path)
    return DiagnosticsBundleResult(path=str(out_path), bundle_sha256=bundle_sha256, manifest=manifest)

