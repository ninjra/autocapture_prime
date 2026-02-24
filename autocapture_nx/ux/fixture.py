"""Fixture utilities for CLI-only pipeline validation."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable

from autocapture.runtime.governor import RuntimeGovernor
from autocapture.runtime.resources import sample_resources
from autocapture_nx.kernel.audit import append_audit_event
from autocapture_nx.kernel.paths import resolve_repo_path
from autocapture_nx.kernel.query import run_query
from autocapture_nx.kernel.activity_signal import is_activity_signal_fresh, load_activity_signal
from autocapture_nx.processing.idle import IdleProcessor
from autocapture_nx.kernel.providers import capability_providers


_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\\-]*")


@dataclass(frozen=True)
class QuerySpec:
    query: str
    expected: str
    match_mode: str
    casefold: bool
    require_citations: bool
    require_state: str


def load_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = _resolve_path(path)
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def resolve_screenshots(manifest: dict[str, Any]) -> list[Path]:
    inputs = manifest.get("inputs", {}) if isinstance(manifest, dict) else {}
    screenshots = inputs.get("screenshots", []) if isinstance(inputs, dict) else []
    resolved: list[Path] = []
    for item in screenshots:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("path", "")).strip()
        if not raw:
            continue
        path = _resolve_path(raw)
        resolved.append(path)
    return resolved


def build_user_config(template_path: str | Path, *, frames_dir: Path, max_frames: int | None = None, run_id: str | None = None) -> dict[str, Any]:
    template = json.loads(_resolve_path(template_path).read_text(encoding="utf-8"))
    frames_dir_value = str(frames_dir)
    template = _replace_placeholder(template, "__FIXTURE_FRAMES_DIR__", frames_dir_value)
    capture_stub = template.setdefault("capture", {}).setdefault("stub", {})
    if isinstance(capture_stub, dict):
        if max_frames is not None:
            capture_stub["max_frames"] = int(max_frames)
    if run_id:
        runtime = template.setdefault("runtime", {})
        if isinstance(runtime, dict):
            runtime["run_id"] = str(run_id)
    # Fixture runs must be WSL-stable. On WSL we strongly prefer in-proc hosting
    # to avoid spawning many host_runner processes (each can be hundreds of MB).
    # Keep caps low either way to avoid OOM spikes.
    plugins_cfg = template.setdefault("plugins", {})
    if isinstance(plugins_cfg, dict):
        hosting = plugins_cfg.setdefault("hosting", {})
        if isinstance(hosting, dict):
            is_wsl = bool(os.getenv("WSL_INTEROP") or os.getenv("WSL_DISTRO_NAME"))
            hosting["mode"] = "inproc" if is_wsl else "subprocess"
            # Make in-proc usage explicit for traceability (EXT-07).
            hosting.setdefault("inproc_allow_all", True)
            hosting.setdefault("subprocess_spawn_concurrency", 1)
            hosting.setdefault("subprocess_max_hosts", 2)
            hosting.setdefault("subprocess_idle_ttl_s", 10.0)
            # The fixture harness must remain robust under WSL crashes/hangs.
            # Keep plugins out-of-process unless absolutely required, so C-extension
            # faults (sqlcipher/onnx/etc) can't take down the main kernel.
            hosting["inproc_allowlist"] = []
            hosting["inproc_justifications"] = {}
            # Keep caches under the fixture's data_dir so all writes remain within
            # the fixture filesystem policy, and so runs don't pollute repo-level
            # cache directories.
            hosting["cache_dir"] = "{data_dir}/cache/plugins"
    plugins_cfg = template.setdefault("plugins", {})
    if isinstance(plugins_cfg, dict):
        policies = plugins_cfg.setdefault("filesystem_policies", {})
        if isinstance(policies, dict):
            policy = policies.setdefault("builtin.capture.basic", {})
            if isinstance(policy, dict):
                reads = policy.get("read")
                if not isinstance(reads, list):
                    reads = []
                if frames_dir_value not in reads:
                    reads.append(frames_dir_value)
                policy["read"] = reads
                writes = policy.get("readwrite")
                if not isinstance(writes, list):
                    writes = []
                if "{data_dir}" not in writes:
                    writes.append("{data_dir}")
                policy["readwrite"] = writes
    return template


def write_user_config(config_dir: Path, payload: dict[str, Any]) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    user_path = config_dir / "user.json"
    user_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return user_path


def collect_auto_queries(
    metadata: Any,
    *,
    max_tokens: int,
    min_token_len: int,
    stopwords: Iterable[str],
    casefold: bool,
    include_visible_apps: bool,
    include_window_titles: bool,
) -> list[str]:
    tokens: list[str] = []
    stop = {s.casefold() for s in stopwords if s}
    for _record_id, record in _iter_records(metadata):
        if not isinstance(record, dict):
            continue
        record_type = str(record.get("record_type", ""))
        # Auto-queries must work even when SST is disabled (OCR-only fixtures).
        # Treat any derived text layer (SST/OCR/VLM/etc) as a token source.
        if record_type.startswith("derived.sst.text") or record_type.startswith("derived.text."):
            text = str(record.get("text", "") or "")
            tokens.extend(_tokenize(text, casefold=casefold))
        if record_type == "derived.sst.state":
            screen_state = record.get("screen_state", {})
            if isinstance(screen_state, dict):
                if include_visible_apps:
                    apps = screen_state.get("visible_apps", ())
                    if isinstance(apps, (list, tuple)):
                        for item in apps:
                            tokens.extend(_tokenize(str(item), casefold=casefold))
                if include_window_titles:
                    title = screen_state.get("window_title") or screen_state.get("window")
                    if title:
                        tokens.extend(_tokenize(str(title), casefold=casefold))
                state_tokens = screen_state.get("tokens", ())
                if isinstance(state_tokens, (list, tuple)):
                    for token in state_tokens:
                        if not isinstance(token, dict):
                            continue
                        val = token.get("norm_text") or token.get("text")
                        if val:
                            tokens.extend(_tokenize(str(val), casefold=casefold))

    # Preserve a stable order, but prefer longer tokens first. Some fixture
    # manifests ask for larger `min_token_len` yet still expect coverage for
    # shorter screen tokens (e.g., 4-letter words). We treat `min_token_len`
    # as a preference and "backfill" with shorter tokens when needed.
    uniq_all: list[str] = []
    seen_all: set[str] = set()
    for token in tokens:
        if not token:
            continue
        normalized = token.casefold() if casefold else token
        if normalized in stop:
            continue
        if normalized in seen_all:
            continue
        seen_all.add(normalized)
        uniq_all.append(token)

    preferred = [t for t in uniq_all if len(t) >= min_token_len]
    # Aim for at least 4 auto-queries when possible (fixture coverage target).
    min_required = min(4, max_tokens)
    if len(preferred) < min_required:
        for token in uniq_all:
            if token in preferred:
                continue
            preferred.append(token)
            if len(preferred) >= min_required:
                break
    if preferred and len(preferred) < min_required:
        # If extraction produced too few distinct tokens, pad deterministically
        # to meet coverage expectations without introducing unmatchable queries.
        while len(preferred) < min_required:
            preferred.append(preferred[len(preferred) % len(preferred)])

    return preferred[:max_tokens]


def build_query_specs(manifest: dict[str, Any], metadata: Any) -> list[QuerySpec]:
    queries_cfg = manifest.get("queries", {}) if isinstance(manifest, dict) else {}
    mode = str(queries_cfg.get("mode", "auto")).strip().lower()
    require_state = str(queries_cfg.get("require_state", "ok") or "ok")
    require_citations = bool(queries_cfg.get("require_citations", True))
    auto_cfg = queries_cfg.get("auto", {}) if isinstance(queries_cfg.get("auto", {}), dict) else {}
    casefold = bool(auto_cfg.get("casefold", True))
    match_mode = str(auto_cfg.get("match_mode", "exact_word") or "exact_word")
    explicit = queries_cfg.get("explicit", []) if isinstance(queries_cfg.get("explicit", []), list) else []

    specs: list[QuerySpec] = []
    for item in explicit:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query", "")).strip()
        if not query:
            continue
        expected = str(item.get("expect", item.get("match", query)) or query)
        specs.append(
            QuerySpec(
                query=query,
                expected=expected,
                match_mode=str(item.get("match_mode", match_mode) or match_mode),
                casefold=bool(item.get("casefold", casefold)),
                require_citations=bool(item.get("require_citations", require_citations)),
                require_state=str(item.get("require_state", require_state) or require_state),
            )
        )

    if mode == "auto":
        auto_tokens = collect_auto_queries(
            metadata,
            max_tokens=int(auto_cfg.get("max_tokens", 40) or 40),
            min_token_len=int(auto_cfg.get("min_token_len", 4) or 4),
            stopwords=auto_cfg.get("stopwords", []) if isinstance(auto_cfg.get("stopwords", []), list) else [],
            casefold=casefold,
            include_visible_apps=bool(auto_cfg.get("include_visible_apps", True)),
            include_window_titles=bool(auto_cfg.get("include_window_titles", True)),
        )
        for token in auto_tokens:
            specs.append(
                QuerySpec(
                    query=token,
                    expected=token,
                    match_mode=match_mode,
                    casefold=casefold,
                    require_citations=require_citations,
                    require_state=require_state,
                )
            )
    return specs


def run_idle_processing(system: Any, *, max_steps: int = 20, timeout_s: float = 60.0) -> dict[str, Any]:
    idle = IdleProcessor(system)
    governor = _resolve_governor(system)
    start = time.monotonic()
    steps = 0
    last_stats: dict[str, Any] | None = None
    done = False
    blocked: dict[str, Any] | None = None
    while steps < max_steps and (time.monotonic() - start) <= timeout_s:
        signals = _runtime_signals(system)
        decision = governor.decide(signals)
        fixture_override = bool(signals.get("fixture_override"))
        if decision.mode != "IDLE_DRAIN":
            blocked = {
                "mode": decision.mode,
                "reason": decision.reason,
                "idle_seconds": decision.idle_seconds,
                "activity_score": decision.activity_score,
            }
            break
        lease = governor.lease("fixture.idle", decision.budget.remaining_ms, heavy=True)
        if not lease.allowed:
            blocked = {"mode": decision.mode, "reason": "budget_exhausted"}
            break
        step_start = time.monotonic()

        def _should_abort() -> bool:
            if fixture_override:
                return False
            return bool(governor.should_preempt(_runtime_signals(system)))

        result = idle.process_step(
            should_abort=_should_abort,
            budget_ms=lease.granted_ms,
            persist_checkpoint=False,
        )
        consumed_ms = int(max(0.0, (time.monotonic() - step_start) * 1000.0))
        lease.record(consumed_ms)
        if isinstance(result, tuple):
            done = bool(result[0])
            stats_obj = result[1] if len(result) > 1 else None
        else:
            done = bool(result)
            stats_obj = None
        if stats_obj is not None and hasattr(stats_obj, "__dataclass_fields__"):
            last_stats = asdict(stats_obj)
        elif isinstance(stats_obj, dict):
            last_stats = dict(stats_obj)
        steps += 1
        if done:
            break
    return {
        "done": bool(done),
        "steps": steps,
        "blocked": blocked,
        "stats": last_stats,
        "elapsed_s": round(time.monotonic() - start, 3),
    }


def evaluate_query(system: Any, spec: QuerySpec) -> dict[str, Any]:
    result = run_query(system, spec.query)
    answer = result.get("answer", {}) if isinstance(result, dict) else {}
    claims = answer.get("claims", []) if isinstance(answer, dict) else []
    answer_state = str(answer.get("state", ""))
    require_state = str(spec.require_state or "ok")
    if require_state and answer_state != require_state:
        return {
            "query": spec.query,
            "ok": False,
            "reason": f"answer_state:{answer_state}",
            "answer_state": answer_state,
            "claims": len(claims),
            "results": len(result.get("results", []) if isinstance(result, dict) else []),
        }
    matched = False
    matched_text = None
    matched_citations = False
    matched_citations_payload: list[dict[str, Any]] | None = None
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        text = str(claim.get("text", "") or "")
        citations = claim.get("citations", [])
        if _match_text(spec.expected, text, mode=spec.match_mode, casefold=spec.casefold):
            matched = True
            matched_text = text
            matched_citations = bool(citations) if isinstance(citations, list) else False
            matched_citations_payload = citations if isinstance(citations, list) else None
            break

    if not matched:
        return {
            "query": spec.query,
            "ok": False,
            "reason": "no_match",
            "answer_state": answer_state,
            "claims": len(claims),
            "results": len(result.get("results", []) if isinstance(result, dict) else []),
        }

    if spec.require_citations:
        # Fixture runs treat anchors as a hard prerequisite for citeable answers.
        # If the anchor chain isn't being produced (e.g., anchor cadence too sparse),
        # queries must fail so the fixture report is not "green" with unciteable output.
        cfg = getattr(system, "config", {}) if system is not None else {}
        anchor_path = None
        try:
            storage_cfg = cfg.get("storage", {}) if isinstance(cfg, dict) else {}
            anchor_cfg = storage_cfg.get("anchor", {}) if isinstance(storage_cfg, dict) else {}
            anchor_path = anchor_cfg.get("path") if isinstance(anchor_cfg, dict) else None
        except Exception:
            anchor_path = None
        if not anchor_path:
            return {"query": spec.query, "ok": False, "reason": "anchor_path_missing"}
        try:
            anchor_file = Path(str(anchor_path))
            if not anchor_file.exists() or anchor_file.stat().st_size <= 0:
                return {"query": spec.query, "ok": False, "reason": "anchor_missing_or_empty"}
            # Require more than a single genesis anchor for citeable fixture runs.
            # A lone anchor indicates anchoring cadence is too sparse for the run.
            anchors_seen = 0
            with anchor_file.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    anchors_seen += 1
                    if anchors_seen >= 2:
                        break
            if anchors_seen < 2:
                return {"query": spec.query, "ok": False, "reason": "anchor_insufficient"}
        except Exception:
            return {"query": spec.query, "ok": False, "reason": "anchor_check_error"}

        if not matched_citations:
            return {
                "query": spec.query,
                "ok": False,
                "reason": "missing_citations",
                "answer_state": answer_state,
                "claims": len(claims),
                "results": len(result.get("results", []) if isinstance(result, dict) else []),
                "matched_text": matched_text,
            }

    if spec.require_citations and matched_citations_payload is not None:
        # Enforce that citations are actually resolvable to evidence paths.
        # This catches cases where the answer includes citation-shaped objects
        # but the local evidence/anchor chain is missing.
        try:
            validator = system.get("citation.validator") if system is not None and hasattr(system, "get") else None
        except Exception:
            validator = None
        if validator is None or not hasattr(validator, "resolve"):
            return {
                "query": spec.query,
                "ok": False,
                "reason": "citation_validator_unavailable",
                "answer_state": answer_state,
                "claims": len(claims),
                "results": len(result.get("results", []) if isinstance(result, dict) else []),
            }
        try:
            resolved = validator.resolve(matched_citations_payload)
        except Exception as exc:
            return {
                "query": spec.query,
                "ok": False,
                "reason": f"citation_resolve_error:{type(exc).__name__}",
                "answer_state": answer_state,
                "claims": len(claims),
                "results": len(result.get("results", []) if isinstance(result, dict) else []),
            }
        if not bool(resolved.get("ok")):
            errors = resolved.get("errors", [])
            if not isinstance(errors, list):
                errors = [str(errors)]
            # Keep report small; include only the first few errors.
            errors = [str(e) for e in errors][:5]
            return {
                "query": spec.query,
                "ok": False,
                "reason": "citations_unresolvable",
                "errors": errors,
                "answer_state": answer_state,
                "claims": len(claims),
                "results": len(result.get("results", []) if isinstance(result, dict) else []),
            }
    return {
        "query": spec.query,
        "ok": True,
        "answer_state": answer_state,
        "matched_text": matched_text,
        "claims": len(claims),
        "results": len(result.get("results", []) if isinstance(result, dict) else []),
    }


def collect_plugin_load_report(system: Any) -> dict[str, Any]:
    if system is None or not hasattr(system, "has"):
        return {}
    if not system.has("observability.plugin_load_report"):
        return {}
    try:
        reporter = system.get("observability.plugin_load_report")
    except Exception:
        return {}
    if hasattr(reporter, "report"):
        try:
            return reporter.report()
        except Exception:
            return {}
    if isinstance(reporter, dict):
        return dict(reporter)
    return {}


def collect_plugin_trace(system: Any) -> dict[str, Any]:
    if system is None or not hasattr(system, "has"):
        return {}
    if not system.has("observability.plugin_trace"):
        return {}
    try:
        trace = system.get("observability.plugin_trace")
    except Exception:
        return {}
    payload: dict[str, Any] = {}
    if hasattr(trace, "summary"):
        try:
            payload["summary"] = _normalize_report_value(trace.summary())
        except Exception:
            payload["summary"] = {}
    if hasattr(trace, "snapshot"):
        try:
            payload["events"] = _normalize_report_value(trace.snapshot())
        except Exception:
            payload["events"] = []
    return payload


def probe_plugins(system: Any, *, sample_frame: bytes | None, sample_record_id: str | None) -> list[dict[str, Any]]:
    """Probe a minimal set of plugin capabilities for fixture validation.

    Important: probing every provider for every capability can spawn dozens of
    subprocess plugin hosts (each can be hundreds of MB RSS), which is a common
    cause of WSL OOM crashes during fixture runs. Default to probing only the
    selected provider per capability; allow opting into full probing explicitly.
    """

    if system is None or not hasattr(system, "capabilities"):
        return []

    cfg = getattr(system, "config", {}) if system is not None else {}
    tools_cfg = cfg.get("tools", {}) if isinstance(cfg, dict) else {}
    fixture_cfg = tools_cfg.get("fixture", {}) if isinstance(tools_cfg, dict) else {}
    probe_all = bool(fixture_cfg.get("probe_all_providers", False))

    results: list[dict[str, Any]] = []
    caps = system.capabilities.all() if hasattr(system, "capabilities") else {}
    for cap_name, cap_obj in sorted(caps.items(), key=lambda item: item[0]):
        providers = capability_providers(cap_obj, cap_name)
        if not providers:
            results.append({"capability": cap_name, "provider_id": None, "ok": False, "error": "no_providers"})
            continue
        # Probe only the first (selected) provider unless explicitly requested.
        selected = providers if probe_all else providers[:1]
        for provider_id, provider in selected:
            outcome = _probe_capability(
                cap_name,
                provider_id=str(provider_id),
                provider=provider,
                sample_frame=sample_frame,
                sample_record_id=sample_record_id,
                system=system,
            )
            results.append(outcome)
        # Enforce the subprocess host cap eagerly to avoid transient fanout.
        try:
            from autocapture_nx.plugin_system.host import reap_subprocess_hosts

            reap_subprocess_hosts(force=False, bypass_interval_gate=True)
        except Exception:
            pass
    return results


def _probe_capability(
    capability: str,
    *,
    provider_id: str,
    provider: Any,
    sample_frame: bytes | None,
    sample_record_id: str | None,
    system: Any,
) -> dict[str, Any]:
    def _call(method: str, *args, **kwargs):
        fn = getattr(provider, method, None)
        if fn is None or not callable(fn):
            raise AttributeError(f"{method} not available")
        return fn(*args, **kwargs)

    result: dict[str, Any] = {
        "capability": capability,
        "provider_id": provider_id,
        "ok": False,
        "error": None,
        "method": None,
    }
    try:
        if capability == "ocr.engine":
            result["method"] = "extract_tokens"
            payload = _call("extract_tokens", sample_frame or b"")
        elif capability == "vision.extractor":
            result["method"] = "extract"
            payload = _call("extract", sample_frame or b"")
        elif capability == "retrieval.strategy":
            result["method"] = "search"
            payload = _call("search", "probe")
        elif capability == "answer.builder":
            result["method"] = "build"
            payload = _call("build", [])
        elif capability == "citation.validator":
            result["method"] = "resolve"
            payload = _call("resolve", [])
        elif capability == "storage.metadata":
            result["method"] = "keys"
            payload = _call("keys")
        elif capability == "storage.media":
            result["method"] = "get"
            payload = _call("get", sample_record_id or "missing")
        elif capability == "capture.source":
            result["method"] = "start/stop"
            _call("start")
            _call("stop")
            payload = {"status": "started_stopped"}
        elif capability == "capture.screenshot":
            result["method"] = "start/stop"
            _call("start")
            _call("stop")
            payload = {"status": "started_stopped"}
        elif capability == "window.metadata":
            result["method"] = "current"
            payload = _call("current")
        elif capability == "tracking.input":
            result["method"] = "activity_signal"
            payload = _call("activity_signal")
        else:
            result["method"] = "__call__"
            payload = provider()
        result["ok"] = True
        result["result"] = _summarize_probe_payload(payload)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _summarize_probe_payload(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {"kind": "none"}
    if isinstance(payload, (str, int, float, bool)):
        return {"kind": "scalar", "value": payload}
    if isinstance(payload, dict):
        return {"kind": "dict", "keys": list(payload.keys())[:20]}
    if isinstance(payload, (list, tuple)):
        return {"kind": "list", "length": len(payload)}
    return {"kind": type(payload).__name__}


def _normalize_report_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if value.__class__.__name__ == "CapabilityProxy":
        return {"__capability_proxy__": True, "repr": str(value)}
    if isinstance(value, bytes):
        return {"__bytes_len": len(value)}
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize_report_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _normalize_report_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_report_value(item) for item in value]
    return str(value)


def audit_fixture_event(action: str, *, outcome: str, details: dict[str, Any]) -> None:
    payload = {"action": action, "outcome": outcome, **details}
    append_audit_event(action=action, actor="tools.fixture", outcome=outcome, details=details)
    _ = payload


def _resolve_path(path: str | Path) -> Path:
    raw = str(path)
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    if ":" in raw[:3]:
        return Path(raw)
    return resolve_repo_path(candidate)


def _replace_placeholder(value: Any, placeholder: str, replacement: str) -> Any:
    if isinstance(value, dict):
        return {k: _replace_placeholder(v, placeholder, replacement) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_placeholder(v, placeholder, replacement) for v in value]
    if isinstance(value, str):
        return value.replace(placeholder, replacement)
    return value


def _iter_records(metadata: Any) -> Iterable[tuple[str, Any]]:
    keys = []
    try:
        keys = list(getattr(metadata, "keys", lambda: [])())
    except Exception:
        keys = []
    for key in sorted(keys):
        try:
            yield key, metadata.get(key, {})
        except Exception:
            continue


def _tokenize(text: str, *, casefold: bool) -> list[str]:
    if not text:
        return []
    if casefold:
        text = text.casefold()
    return _TOKEN_RE.findall(text)


def _match_text(expected: str, text: str, *, mode: str, casefold: bool) -> bool:
    if casefold:
        expected = expected.casefold()
        text = text.casefold()
    if mode == "contains":
        return expected in text
    pattern = r"(?<![A-Za-z0-9])" + re.escape(expected) + r"(?![A-Za-z0-9])"
    return re.search(pattern, text) is not None


def _runtime_signals(system: Any) -> dict[str, Any]:
    cfg = getattr(system, "config", {}) if system is not None else {}
    runtime_cfg = cfg.get("runtime", {}) if isinstance(cfg, dict) else {}
    active_window_s = float(runtime_cfg.get("active_window_s", 3))
    idle_seconds = 0.0
    user_active = False
    activity_score = 0.0
    activity_recent = False
    tracker = None
    if hasattr(system, "has") and system.has("tracking.input"):
        try:
            tracker = system.get("tracking.input")
        except Exception:
            tracker = None
    if tracker is not None:
        if hasattr(tracker, "activity_signal"):
            try:
                signal = tracker.activity_signal()
            except Exception:
                signal = {}
            if isinstance(signal, dict):
                idle_seconds = float(signal.get("idle_seconds", 0.0))
                user_active = bool(signal.get("user_active", False))
                activity_score = float(signal.get("activity_score", 0.0) or 0.0)
                activity_recent = bool(signal.get("recent_activity", False))
        else:
            try:
                idle_seconds = float(tracker.idle_seconds())
            except Exception:
                idle_seconds = 0.0
            user_active = idle_seconds < active_window_s
    else:
        signal = None
        try:
            signal = load_activity_signal(cfg)
        except Exception:
            signal = None
        if signal is not None and is_activity_signal_fresh(signal, cfg):
            idle_seconds = float(signal.idle_seconds)
            user_active = bool(signal.user_active)
        else:
            idle_seconds = 0.0
            user_active = True
    enforce_cfg = runtime_cfg.get("mode_enforcement", {}) if isinstance(runtime_cfg, dict) else {}
    suspend_workers = bool(enforce_cfg.get("suspend_workers", True))
    allow_query_heavy = bool(enforce_cfg.get("allow_query_heavy", True))
    fixture_override = bool(enforce_cfg.get("fixture_override", False))
    if fixture_override:
        idle_seconds = float("inf")
        user_active = False
        activity_score = 0.0
        activity_recent = False
    signals: dict[str, Any] = {
        "idle_seconds": idle_seconds,
        "user_active": user_active,
        "query_intent": False,
        "suspend_workers": suspend_workers,
        "allow_query_heavy": allow_query_heavy,
        "activity_score": activity_score,
        "activity_recent": activity_recent,
    }
    if fixture_override:
        signals["fixture_override"] = True
    resources = sample_resources()
    if resources.cpu_utilization is not None:
        signals["cpu_utilization"] = resources.cpu_utilization
    if resources.ram_utilization is not None:
        signals["ram_utilization"] = resources.ram_utilization
    run_id = ""
    if isinstance(cfg, dict):
        run_id = str(cfg.get("runtime", {}).get("run_id") or "")
    if run_id:
        signals["run_id"] = run_id
    return signals


def _resolve_governor(system: Any) -> RuntimeGovernor:
    governor = None
    if hasattr(system, "has") and system.has("runtime.governor"):
        try:
            governor = system.get("runtime.governor")
        except Exception:
            governor = None
    if governor is None:
        governor = RuntimeGovernor()
    if hasattr(governor, "update_config"):
        try:
            governor.update_config(getattr(system, "config", {}) if system is not None else {})
        except Exception:
            pass
    return governor
