"""Doctor/health report helpers (EXEC-08, OPS-04).

This module builds a stable health summary plus a component matrix that can be
used by `/api/health` and operator tooling without triggering heavy work.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ComponentHealth:
    name: str
    ok: bool
    detail: str
    last_error_code: str | None = None
    checked_at_utc: str | None = None


def _has_cap(caps: dict[str, Any], name: str) -> bool:
    try:
        return name in caps
    except Exception:
        return False


def build_component_matrix(*, system: Any, checks: list[Any] | None = None) -> list[ComponentHealth]:
    caps = {}
    try:
        caps = system.capabilities.all()
    except Exception:
        caps = {}
    checked = _utc_now_iso()

    components: list[ComponentHealth] = []

    # Pipeline capability checks (minimal, presence-based).
    # Capture is optional when disabled in config (sidecar mode). If this repo is
    # configured to capture locally, require the relevant capture capabilities.
    want_capture = True
    try:
        cfg = getattr(system, "config", None)
        if isinstance(cfg, dict):
            capture_cfg = cfg.get("capture", {}) if isinstance(cfg.get("capture"), dict) else {}
            want_screenshot = bool((capture_cfg.get("screenshot") or {}).get("enabled", False)) if isinstance(capture_cfg, dict) else False
            want_audio = bool((capture_cfg.get("audio") or {}).get("enabled", False)) if isinstance(capture_cfg, dict) else False
            want_video = bool((capture_cfg.get("video") or {}).get("enabled", False)) if isinstance(capture_cfg, dict) else False
            want_capture = bool(want_screenshot or want_audio or want_video)
    except Exception:
        want_capture = True
    if want_capture:
        capture_ok = _has_cap(caps, "capture.source") or _has_cap(caps, "capture.screenshot") or _has_cap(caps, "capture.audio")
        capture_detail = "ok" if capture_ok else "missing capture.source/capture.screenshot/capture.audio"
    else:
        capture_ok = True
        capture_detail = "disabled"
    components.append(
        ComponentHealth(
            name="capture",
            ok=bool(capture_ok),
            detail=capture_detail,
            checked_at_utc=checked,
        )
    )

    ocr_ok = _has_cap(caps, "ocr.engine")
    components.append(
        ComponentHealth(
            name="ocr",
            ok=bool(ocr_ok),
            detail="ok" if ocr_ok else "missing ocr.engine",
            checked_at_utc=checked,
        )
    )

    vlm_ok = _has_cap(caps, "vision.extractor")
    components.append(
        ComponentHealth(
            name="vlm",
            ok=bool(vlm_ok),
            detail="ok" if vlm_ok else "missing vision.extractor",
            checked_at_utc=checked,
        )
    )

    indexing_ok = _has_cap(caps, "embedder.text") and _has_cap(caps, "storage.metadata")
    components.append(
        ComponentHealth(
            name="indexing",
            ok=bool(indexing_ok),
            detail="ok" if indexing_ok else "missing embedder.text or storage.metadata",
            checked_at_utc=checked,
        )
    )

    retrieval_ok = _has_cap(caps, "retrieval.strategy")
    components.append(
        ComponentHealth(
            name="retrieval",
            ok=bool(retrieval_ok),
            detail="ok" if retrieval_ok else "missing retrieval.strategy",
            checked_at_utc=checked,
        )
    )

    answer_ok = _has_cap(caps, "answer.builder") and _has_cap(caps, "citation.validator")
    components.append(
        ComponentHealth(
            name="answer",
            ok=bool(answer_ok),
            detail="ok" if answer_ok else "missing answer.builder or citation.validator",
            checked_at_utc=checked,
        )
    )

    # Storage/ledger essentials for citeability.
    store_ok = _has_cap(caps, "storage.metadata") and _has_cap(caps, "storage.media")
    components.append(
        ComponentHealth(
            name="storage",
            ok=bool(store_ok),
            detail="ok" if store_ok else "missing storage.metadata or storage.media",
            checked_at_utc=checked,
        )
    )
    ledger_ok = _has_cap(caps, "ledger.writer") and _has_cap(caps, "journal.writer") and _has_cap(caps, "anchor.writer")
    components.append(
        ComponentHealth(
            name="ledger",
            ok=bool(ledger_ok),
            detail="ok" if ledger_ok else "missing ledger.writer/journal.writer/anchor.writer",
            checked_at_utc=checked,
        )
    )

    # Best-effort: fold kernel.doctor() checks into "kernel" component.
    if checks:
        failed = [c for c in checks if getattr(c, "ok", True) is False]
        ok = not failed
        detail = "ok" if ok else f"failed_checks:{','.join(str(getattr(c,'name','')) for c in failed[:5])}"
        components.append(ComponentHealth(name="kernel", ok=ok, detail=detail, checked_at_utc=checked))

    # Stable order.
    components.sort(key=lambda c: c.name)
    return components


def build_health_report(*, system: Any, checks: list[Any]) -> dict[str, Any]:
    generated = _utc_now_iso()
    matrix = build_component_matrix(system=system, checks=checks)
    ok = all(bool(item.ok) for item in matrix) and all(bool(getattr(c, "ok", True)) for c in (checks or []))
    failed_components = [item.name for item in matrix if not bool(item.ok)]
    failed_checks = [str(getattr(c, "name", "")) for c in (checks or []) if getattr(c, "ok", True) is False]
    summary = {
        "ok": bool(ok),
        "code": "ok" if ok else "degraded",
        "components_total": int(len(matrix)),
        "components_ok": int(sum(1 for item in matrix if item.ok)),
        "checks_total": int(len(checks or [])),
        "checks_failed": int(sum(1 for c in (checks or []) if getattr(c, "ok", True) is False)),
    }
    summary["message"] = (
        f"components_ok={summary['components_ok']}/{summary['components_total']} "
        f"checks_failed={summary['checks_failed']}/{summary['checks_total']}"
        + (f" failed_components={failed_components[:5]}" if failed_components else "")
        + (f" failed_checks={failed_checks[:5]}" if failed_checks else "")
    )
    return {
        "ok": bool(ok),
        "generated_at_utc": generated,
        "summary": summary,
        "components": [asdict(item) for item in matrix],
        # Preserve raw checks for backwards compatibility.
        "checks": [getattr(check, "__dict__", {"name": getattr(check, "name", ""), "ok": getattr(check, "ok", False)}) for check in (checks or [])],
    }
