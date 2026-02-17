"""PromptOps optimization layer for prompt handling."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Iterable

from autocapture.core.hashing import hash_text
from autocapture_nx.plugin_system.registry import PluginRegistry
from autocapture.promptops.evaluate import evaluate_prompt
from autocapture.promptops.github import create_pull_request
from autocapture.promptops.propose import propose_prompt
from autocapture.promptops.sources import PromptBundle, snapshot_sources
from autocapture.promptops.validate import DEFAULT_BANNED, validate_prompt


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)


def _data_root(config: dict[str, Any]) -> Path:
    paths = config.get("paths", {}) if isinstance(config, dict) else {}
    data_dir = paths.get("data_dir") or config.get("storage", {}).get("data_dir", "data")
    return Path(data_dir)


@dataclass
class PromptOpsResult:
    prompt_id: str
    prompt: str
    applied: bool
    mode: str
    proposal: dict[str, Any] | None
    validation: dict[str, Any] | None
    evaluation: dict[str, Any] | None
    sources: list[dict[str, Any]]
    trace: dict[str, Any] | None = None


class PromptStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, str] = {}

    def _path(self, prompt_id: str) -> Path:
        return self.root / f"{_safe_name(prompt_id)}.txt"

    def get(self, prompt_id: str) -> str | None:
        if prompt_id in self._cache:
            return self._cache[prompt_id]
        path = self._path(prompt_id)
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        self._cache[prompt_id] = text
        return text

    def set(self, prompt_id: str, text: str) -> Path:
        path = self._path(prompt_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self._cache[prompt_id] = text
        return path


class PromptHistory:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def record(self, prompt_id: str, payload: dict[str, Any]) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = f"{_safe_name(prompt_id)}_{stamp}.json"
        path = self.root / name
        path.write_text(_safe_json(payload), encoding="utf-8")
        return path


def _safe_json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True)


class PromptOpsLayer:
    """Applies PromptOps validation + proposals to prompts."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._bundle_instance: PromptBundle | None = None
        self._bundle_loaded = False
        self._store = PromptStore(self._prompt_dir())
        self._history = PromptHistory(self._history_dir())

    def _prompt_cfg(self) -> dict[str, Any]:
        return self._config.get("promptops", {}) if isinstance(self._config, dict) else {}

    def _prompt_dir(self) -> Path:
        cfg = self._prompt_cfg()
        root = _data_root(self._config)
        return Path(cfg.get("prompt_dir") or root / "promptops" / "prompts")

    def _history_dir(self) -> Path:
        cfg = self._prompt_cfg()
        root = _data_root(self._config)
        return Path(cfg.get("history_dir") or root / "promptops" / "history")

    def _metrics_cfg(self) -> dict[str, Any]:
        cfg = self._prompt_cfg()
        metrics = cfg.get("metrics", {})
        return metrics if isinstance(metrics, dict) else {}

    def _metrics_path(self) -> Path:
        metrics_cfg = self._metrics_cfg()
        raw = metrics_cfg.get("output_path")
        if raw:
            return Path(str(raw))
        root = _data_root(self._config)
        return root / "promptops" / "metrics.jsonl"

    def _append_metric(self, payload: dict[str, Any]) -> None:
        metrics_cfg = self._metrics_cfg()
        if not bool(metrics_cfg.get("enabled", False)):
            return
        try:
            path = self._metrics_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            row = dict(payload)
            row.setdefault("ts_utc", datetime.now(timezone.utc).isoformat())
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        except Exception:
            return

    def _bundle_name(self) -> str:
        cfg = self._prompt_cfg()
        return str(cfg.get("bundle_name", "default"))

    def _bundle_root(self) -> Path | None:
        cfg = self._prompt_cfg()
        raw = cfg.get("bundle_root")
        if not raw:
            return None
        return Path(str(raw))

    def _bundle_plugin_id(self) -> str:
        name = self._bundle_name().strip()
        if not name:
            return ""
        if "." in name:
            return name
        return f"builtin.prompt.bundle.{name}"

    def _scoped_plugin_config(self, plugin_ids: list[str]) -> dict[str, Any]:
        if not isinstance(self._config, dict):
            return {}
        scoped = deepcopy(self._config)
        plugins_cfg = scoped.setdefault("plugins", {})
        plugins_cfg["allowlist"] = list(plugin_ids)
        plugins_cfg["enabled"] = {pid: True for pid in plugin_ids}
        plugins_cfg["default_pack"] = list(plugin_ids)
        return scoped

    def _prepare_sources(self, sources: Iterable[Any]) -> list[Any]:
        root = self._bundle_root()
        prepared: list[Any] = []
        for src in sources:
            if isinstance(src, dict):
                entry = dict(src)
            elif isinstance(src, str):
                entry = {"path": src}
            else:
                entry = {"text": str(src)}
            path_value = entry.get("path")
            if path_value and root:
                try:
                    path_obj = Path(str(path_value))
                    if not path_obj.is_absolute():
                        entry["path"] = str(root / path_obj)
                except Exception:
                    pass
            if "path" in entry and "text" not in entry and "bytes" not in entry and "url" not in entry:
                path = Path(str(entry["path"]))
                entry["bytes"] = path.read_bytes() if path.exists() else b""
            prepared.append(entry)
        return prepared

    def _load_bundle(self) -> PromptBundle | None:
        if self._bundle_loaded:
            return self._bundle_instance
        plugin_id = self._bundle_plugin_id()
        if not plugin_id:
            self._bundle_loaded = True
            return None
        try:
            scoped = self._scoped_plugin_config([plugin_id])
            registry = PluginRegistry(
                scoped,
                safe_mode=bool(scoped.get("plugins", {}).get("safe_mode", False)),
            )
            plugins, capabilities = registry.load_plugins()
            bundle = None
            for plugin in plugins:
                if plugin.plugin_id != plugin_id:
                    continue
                if isinstance(plugin.capabilities, dict):
                    bundle = plugin.capabilities.get("prompt.bundle")
                if bundle is not None:
                    break
            if bundle is None:
                try:
                    bundle = capabilities.get("prompt.bundle")
                except Exception:
                    bundle = None
            self._bundle_instance = bundle
        except Exception:
            self._bundle_instance = None
        self._bundle_loaded = True
        return self._bundle_instance

    def _snapshot(self, sources: Iterable[Any]) -> dict[str, Any]:
        bundle = self._load_bundle()
        prepared = self._prepare_sources(sources)
        if bundle is not None:
            try:
                return bundle.snapshot(prepared)
            except Exception:
                pass
        return snapshot_sources(prepared)

    def _examples_for(self, prompt_id: str) -> list[dict[str, Any]]:
        cfg = self._prompt_cfg()
        examples = cfg.get("examples", {})
        if isinstance(examples, dict):
            return list(examples.get(prompt_id, []))
        if isinstance(examples, list):
            return list(examples)
        return []

    def _record_template_mapping(self, prompt_id: str, snapshot: dict[str, Any]) -> None:
        sources = snapshot.get("sources", [])
        if not isinstance(sources, list):
            return
        combined_hash = snapshot.get("combined_hash")
        try:
            from autocapture_nx.kernel.audit import PluginAuditLog

            audit = PluginAuditLog.from_config(self._config)
            audit.record_template_diff(
                mapping_id=str(prompt_id),
                mapping_kind="promptops.sources",
                sources=[item for item in sources if isinstance(item, dict)],
                combined_hash=str(combined_hash) if combined_hash is not None else None,
            )
        except Exception:
            return

    def prepare_prompt(
        self,
        prompt: str,
        *,
        prompt_id: str = "default",
        sources: Iterable[Any] | None = None,
        examples: list[dict[str, Any]] | None = None,
        persist: bool | None = None,
        strategy: str | None = None,
        prefer_stored_prompt: bool = True,
    ) -> PromptOpsResult:
        start = time.perf_counter()
        cfg = self._prompt_cfg()
        enabled = bool(cfg.get("enabled", True))
        mode = str(cfg.get("mode", "auto_apply"))
        trace: dict[str, Any] = {
            "strategy": str(strategy or cfg.get("strategy", "append_sources")),
            "stages_ms": {},
            "enabled": bool(enabled),
            "mode": str(mode),
        }
        if not enabled or mode == "off":
            trace["stages_ms"]["total"] = round((time.perf_counter() - start) * 1000.0, 3)
            self._append_metric(
                {
                    "type": "promptops.prepare_prompt",
                    "prompt_id": prompt_id,
                    "enabled": False,
                    "mode": mode,
                    "applied": False,
                    "trace": trace,
                    "latency_ms": round((time.perf_counter() - start) * 1000.0, 3),
                }
            )
            return PromptOpsResult(
                prompt_id=prompt_id,
                prompt=prompt,
                applied=False,
                mode=mode,
                proposal=None,
                validation=None,
                evaluation=None,
                sources=[],
                trace=trace,
            )

        sources = list(cfg.get("sources", []) if sources is None else sources)
        stage_start = time.perf_counter()
        snapshot = self._snapshot(sources)
        trace["stages_ms"]["snapshot"] = round((time.perf_counter() - stage_start) * 1000.0, 3)
        snapshot_sources_list = list(snapshot.get("sources", []))
        self._record_template_mapping(prompt_id, snapshot)
        if strategy is None:
            strategy = str(cfg.get("strategy", "append_sources"))
        if strategy == "append_sources" and not snapshot_sources_list:
            strategy = "none"
        trace["strategy"] = str(strategy)
        trace["source_count"] = int(len(snapshot_sources_list))

        stored_prompt = self._store.get(prompt_id) if prefer_stored_prompt else None
        current_prompt = stored_prompt or prompt
        stage_start = time.perf_counter()
        proposal = propose_prompt(current_prompt, snapshot, strategy=strategy)
        trace["stages_ms"]["propose"] = round((time.perf_counter() - stage_start) * 1000.0, 3)
        candidate = proposal.get("proposal", current_prompt)

        stage_start = time.perf_counter()
        validation = validate_prompt(
            candidate,
            max_chars=int(cfg.get("max_chars", 8000)),
            max_tokens=int(cfg.get("max_tokens", 2000)),
            banned_patterns=cfg.get("banned_patterns", DEFAULT_BANNED),
        )
        trace["stages_ms"]["validate"] = round((time.perf_counter() - stage_start) * 1000.0, 3)
        min_pass_rate = cfg.get("min_pass_rate")
        if min_pass_rate is None:
            pct = int(cfg.get("min_pass_rate_pct", 100))
            min_pass_rate = max(0.0, min(1.0, pct / 100.0))
        eval_examples = examples if examples is not None else self._examples_for(prompt_id)
        stage_start = time.perf_counter()
        evaluation = evaluate_prompt(
            candidate,
            eval_examples,
            min_pass_rate=float(min_pass_rate),
            require_citations=bool(cfg.get("require_citations", True)),
        )
        trace["stages_ms"]["evaluate"] = round((time.perf_counter() - stage_start) * 1000.0, 3)
        ok = bool(validation.get("ok")) and bool(evaluation.get("ok"))
        trace["validation_ok"] = bool(validation.get("ok"))
        trace["evaluation_ok"] = bool(evaluation.get("ok"))
        trace["confidence"] = float(round(float(evaluation.get("pass_rate", 0.0) or 0.0), 4))

        persist_default = bool(cfg.get("persist_prompts", False))
        persist = persist_default if persist is None else bool(persist)
        applied = False
        selected_prompt = current_prompt
        if ok and mode in ("auto_apply", "apply"):
            selected_prompt = candidate
            applied = True
            if persist:
                stage_start = time.perf_counter()
                self._store.set(prompt_id, candidate)
                trace["stages_ms"]["persist"] = round((time.perf_counter() - stage_start) * 1000.0, 3)
            else:
                trace["stages_ms"]["persist"] = 0.0
        else:
            trace["stages_ms"]["persist"] = 0.0

        history_cfg = cfg.get("history", {})
        if history_cfg.get("enabled", True):
            stage_start = time.perf_counter()
            history_payload = {
                "prompt_id": prompt_id,
                "mode": mode,
                "applied": applied,
                "proposal_id": proposal.get("proposal_id"),
                "proposal_hash": hash_text(str(proposal.get("proposal", ""))),
                "validation": validation,
                "evaluation": evaluation,
                "sources": snapshot_sources_list,
            }
            if history_cfg.get("include_prompt", False):
                history_payload["prompt"] = selected_prompt
            self._history.record(prompt_id, history_payload)
            trace["stages_ms"]["history"] = round((time.perf_counter() - stage_start) * 1000.0, 3)
        else:
            trace["stages_ms"]["history"] = 0.0

        github_cfg = cfg.get("github", {})
        if bool(github_cfg.get("enabled", False)) and proposal.get("diff"):
            stage_start = time.perf_counter()
            create_pull_request(
                title=str(github_cfg.get("title", "PromptOps update")),
                body=str(github_cfg.get("body", "Automated prompt update.")),
                diff=str(proposal.get("diff")),
                enabled=True,
                output_path=str(github_cfg.get("output_path", "artifacts/promptops_pr.json")),
            )
            trace["stages_ms"]["github"] = round((time.perf_counter() - stage_start) * 1000.0, 3)
        else:
            trace["stages_ms"]["github"] = 0.0

        trace["applied"] = bool(applied)
        trace["proposal_changed"] = bool(str(candidate) != str(current_prompt))
        trace["used_stored_prompt"] = bool(stored_prompt is not None and prefer_stored_prompt)
        trace["stages_ms"]["total"] = round((time.perf_counter() - start) * 1000.0, 3)

        self._append_metric(
            {
                "type": "promptops.prepare_prompt",
                "prompt_id": prompt_id,
                "enabled": True,
                "mode": mode,
                "strategy": str(strategy),
                "applied": bool(applied),
                "persist": bool(persist),
                "proposal_changed": bool(str(candidate) != str(current_prompt)),
                "validation_ok": bool(validation.get("ok", False)),
                "evaluation_ok": bool(evaluation.get("ok", False)),
                "source_count": int(len(snapshot_sources_list)),
                "confidence": float(round(float(evaluation.get("pass_rate", 0.0) or 0.0), 4)),
                "trace": trace,
                "latency_ms": round((time.perf_counter() - start) * 1000.0, 3),
            }
        )

        return PromptOpsResult(
            prompt_id=prompt_id,
            prompt=selected_prompt,
            applied=applied,
            mode=mode,
            proposal=proposal,
            validation=validation,
            evaluation=evaluation,
            sources=snapshot_sources_list,
            trace=trace,
        )

    def prepare_query(
        self,
        query: str,
        *,
        prompt_id: str = "query.default",
        sources: Iterable[Any] | None = None,
    ) -> PromptOpsResult:
        cfg = self._prompt_cfg()
        strategy = str(cfg.get("query_strategy", "none"))
        persist_query = bool(cfg.get("persist_query_prompts", False))
        return self.prepare_prompt(
            query,
            prompt_id=prompt_id,
            sources=sources,
            persist=persist_query,
            strategy=strategy,
            # Query rewriting must always start from the live user query to avoid
            # stale prompt reuse across different questions.
            prefer_stored_prompt=False,
        )

    def record_model_interaction(
        self,
        *,
        prompt_id: str,
        provider_id: str,
        model: str,
        prompt_input: str,
        prompt_effective: str,
        response_text: str,
        success: bool,
        latency_ms: float,
        error: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cfg = self._prompt_cfg()
        payload: dict[str, Any] = {
            "type": "promptops.model_interaction",
            "prompt_id": str(prompt_id),
            "provider_id": str(provider_id),
            "model": str(model or ""),
            "success": bool(success),
            "latency_ms": float(round(float(latency_ms), 3)),
            "error": str(error or ""),
            "input_chars": int(len(str(prompt_input or ""))),
            "effective_chars": int(len(str(prompt_effective or ""))),
            "response_chars": int(len(str(response_text or ""))),
            "response_has_json": bool("{" in str(response_text or "") and "}" in str(response_text or "")),
        }
        if isinstance(metadata, dict) and metadata:
            payload["meta"] = metadata
        self._append_metric(payload)

        review_cfg = cfg.get("review", {})
        if not isinstance(review_cfg, dict) or not bool(review_cfg.get("enabled", False)):
            return {"reviewed": False, "updated": False}
        if bool(review_cfg.get("on_failure_only", True)) and bool(success):
            return {"reviewed": False, "updated": False}
        review_out = self._review_with_model(
            prompt_input=str(prompt_input or ""),
            prompt_effective=str(prompt_effective or ""),
            response_text=str(response_text or ""),
            error=str(error or ""),
            provider_id=str(provider_id),
            model=str(model or ""),
            review_cfg=review_cfg,
        )
        candidate = ""
        review_error = ""
        review_meta: dict[str, Any] = {}
        if isinstance(review_out, str):
            candidate = str(review_out or "")
        elif isinstance(review_out, dict):
            candidate = str(review_out.get("candidate") or "")
            review_error = str(review_out.get("error") or "")
            if isinstance(review_out.get("meta"), dict):
                review_meta = dict(review_out.get("meta") or {})

        if not candidate:
            self._append_metric(
                {
                    "type": "promptops.review_result",
                    "prompt_id": str(prompt_id),
                    "updated": False,
                    "pending_approval": False,
                    "approval_required": not bool(review_cfg.get("auto_approve", False)),
                    "approved": False,
                    "validation_ok": False,
                    "evaluation_ok": False,
                    "review_error": str(review_error or "no_candidate"),
                    "meta": review_meta,
                }
            )
            return {
                "reviewed": True,
                "updated": False,
                "pending_approval": False,
                "approval_required": not bool(review_cfg.get("auto_approve", False)),
            }
        validation = validate_prompt(
            candidate,
            max_chars=int(cfg.get("max_chars", 8000)),
            max_tokens=int(cfg.get("max_tokens", 2000)),
            banned_patterns=cfg.get("banned_patterns", DEFAULT_BANNED),
        )
        eval_examples = self._examples_for(str(prompt_id))
        eval_out = evaluate_prompt(
            candidate,
            eval_examples,
            min_pass_rate=float(max(0.0, min(1.0, float(int(cfg.get("min_pass_rate_pct", 100)) / 100.0)))),
            require_citations=bool(cfg.get("require_citations", True)),
        )
        allow_empty_examples = bool(review_cfg.get("allow_empty_examples", False))
        eval_total = int(eval_out.get("total", 0) or 0)
        if eval_total <= 0 and not allow_empty_examples:
            eval_out["ok"] = False
            eval_out["error"] = "insufficient_examples_for_review_update"
        updated = False
        approval_required = not bool(review_cfg.get("auto_approve", False))
        approved_prompt_ids = review_cfg.get("approved_prompt_ids", [])
        approved_set = {
            str(item).strip()
            for item in (approved_prompt_ids if isinstance(approved_prompt_ids, list) else [])
            if str(item).strip()
        }
        is_approved = (not approval_required) or (str(prompt_id).strip() in approved_set)
        pending_approval = False
        if bool(validation.get("ok", False)) and bool(eval_out.get("ok", False)):
            if bool(review_cfg.get("persist_prompts", True)) and bool(is_approved):
                self._store.set(str(prompt_id), str(candidate))
                updated = True
            elif bool(review_cfg.get("persist_prompts", True)) and not bool(is_approved):
                pending_approval = True
        self._append_metric(
            {
                "type": "promptops.review_result",
                "prompt_id": str(prompt_id),
                "updated": bool(updated),
                "pending_approval": bool(pending_approval),
                "approval_required": bool(approval_required),
                "approved": bool(is_approved),
                "validation_ok": bool(validation.get("ok", False)),
                "evaluation_ok": bool(eval_out.get("ok", False)),
                "evaluation_total": int(eval_total),
                "review_error": str(review_error or ""),
                "meta": review_meta,
            }
        )
        return {
            "reviewed": True,
            "updated": bool(updated),
            "pending_approval": bool(pending_approval),
            "approval_required": bool(approval_required),
        }

    def _review_with_model(
        self,
        *,
        prompt_input: str,
        prompt_effective: str,
        response_text: str,
        error: str,
        provider_id: str,
        model: str,
        review_cfg: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            from autocapture_nx.inference.openai_compat import OpenAICompatClient
            from autocapture_nx.inference.vllm_endpoint import check_external_vllm_ready, enforce_external_vllm_base_url
        except Exception:
            return {"candidate": "", "error": "review_dependencies_unavailable", "meta": {}}
        try:
            base_url = enforce_external_vllm_base_url(str(review_cfg.get("base_url") or "").strip())
        except Exception:
            return {"candidate": "", "error": "review_invalid_base_url", "meta": {}}
        require_preflight = bool(review_cfg.get("require_preflight", True))
        preflight_meta: dict[str, Any] = {}
        if require_preflight:
            preflight = check_external_vllm_ready(
                timeout_completion_s=float(review_cfg.get("preflight_completion_timeout_s") or review_cfg.get("timeout_s") or 15.0),
                require_completion=bool(review_cfg.get("preflight_require_completion", True)),
                retries=int(review_cfg.get("preflight_retries") or 1),
                auto_recover=bool(review_cfg.get("preflight_auto_recover", True)),
            )
            preflight_meta["preflight"] = preflight
            if not bool(preflight.get("ok", False)):
                err = str(preflight.get("error") or preflight.get("initial_error") or "preflight_failed")
                return {"candidate": "", "error": f"review_preflight_failed:{err}", "meta": preflight_meta}
        model_name = str(review_cfg.get("model") or "").strip()
        timeout_s = float(review_cfg.get("timeout_s") or 15.0)
        max_tokens = int(review_cfg.get("max_tokens") or 256)
        api_key = str(review_cfg.get("api_key") or "").strip() or str(
            os.environ.get("AUTOCAPTURE_VLM_API_KEY") or ""
        ).strip() or None
        try:
            client = OpenAICompatClient(base_url=base_url, api_key=api_key, timeout_s=timeout_s)
        except Exception:
            return {"candidate": "", "error": "review_client_init_failed", "meta": preflight_meta}
        if not model_name:
            selected = str(preflight_meta.get("preflight", {}).get("selected_model") or "").strip()
            if selected:
                model_name = selected
        if not model_name:
            try:
                models = client.list_models()
                data = models.get("data", []) if isinstance(models, dict) else []
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    model_name = str(data[0].get("id") or "").strip()
            except Exception:
                model_name = ""
        if not model_name:
            return {"candidate": "", "error": "review_model_not_found", "meta": preflight_meta}
        prompt = (
            "Rewrite the EFFECTIVE_PROMPT to improve grounding and clarity.\n"
            "Keep user intent unchanged. Prefer correctness over speed.\n"
            "Return only rewritten prompt text.\n\n"
            f"PROVIDER: {provider_id}\n"
            f"MODEL: {model}\n"
            f"ERROR: {error}\n"
            f"INPUT_PROMPT:\n{prompt_input}\n\n"
            f"EFFECTIVE_PROMPT:\n{prompt_effective}\n\n"
            f"MODEL_OUTPUT:\n{response_text[:1500]}\n"
        )
        req = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": int(max_tokens),
        }
        try:
            resp = client.chat_completions(req)
        except Exception:
            return {"candidate": "", "error": "review_chat_completion_failed", "meta": preflight_meta}
        choices = resp.get("choices", []) if isinstance(resp, dict) else []
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return {"candidate": "", "error": "review_empty_choices", "meta": preflight_meta}
        msg = choices[0].get("message", {}) if isinstance(choices[0].get("message", {}), dict) else {}
        content = str(msg.get("content") or "").strip()
        if not content:
            return {"candidate": "", "error": "review_empty_content", "meta": preflight_meta}
        cleaned = content.strip().strip("`").strip()
        return {"candidate": cleaned, "error": "", "meta": preflight_meta}
