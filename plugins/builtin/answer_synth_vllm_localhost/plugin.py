"""Citation-friendly answer synthesizer via a localhost OpenAI-compatible LLM.

The synthesizer must not fabricate evidence. It returns claims with explicit
quotes tied to record_ids so the kernel can build verifiable citations.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from autocapture_nx.kernel.paths import resolve_repo_path
from autocapture_nx.inference.openai_compat import OpenAICompatClient
from autocapture_nx.inference.vllm_endpoint import EXTERNAL_VLLM_BASE_URL, enforce_external_vllm_base_url
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


_SYSTEM_PROMPT = (
    "You are a careful assistant answering questions about a user's computer activity. "
    "You MUST use only the provided evidence snippets. "
    "Every claim MUST be backed by at least one exact quote that appears verbatim in an evidence snippet. "
    "If you cannot answer from evidence, return an empty claims list."
)
_QUERY_CONTEXT_PRE_FALLBACK = (
    "Use the user question exactly as written below; do not rewrite intent or entities."
)
_QUERY_CONTEXT_POST_FALLBACK = (
    "After reading the question, answer only from cited evidence snippets and do not invent facts."
)

_DEFAULT_SYSTEM_PROMPT_PATH = "promptops/prompts/answer_synth_system.txt"
_DEFAULT_QUERY_CONTEXT_PRE_PATH = "promptops/prompts/answer_synth_query_pre.txt"
_DEFAULT_QUERY_CONTEXT_POST_PATH = "promptops/prompts/answer_synth_query_post.txt"


def _load_prompt_file(path_hint: str, fallback: str) -> str:
    candidate = str(path_hint or "").strip()
    if not candidate:
        return str(fallback or "")
    paths: list[Path] = []
    raw = Path(candidate)
    paths.append(raw)
    try:
        repo_path = resolve_repo_path(candidate)
        paths.append(repo_path)
    except Exception:
        pass
    seen: set[str] = set()
    for path in paths:
        marker = str(path)
        if marker in seen:
            continue
        seen.add(marker)
        try:
            if not path.exists() or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
        except Exception:
            continue
    return str(fallback or "")


def _truncate(text: str, limit: int) -> str:
    s = str(text or "")
    if len(s) <= int(limit):
        return s
    return s[: max(0, int(limit) - 3)] + "..."


class VllmAnswerSynthesizer(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        self._base_url_policy_error = ""
        try:
            self._base_url = enforce_external_vllm_base_url(cfg.get("base_url"))
        except Exception as exc:
            self._base_url = EXTERNAL_VLLM_BASE_URL
            self._base_url_policy_error = f"invalid_vllm_base_url:{type(exc).__name__}:{exc}"
        self._api_key = str(cfg.get("api_key") or "").strip() or None
        self._model = str(cfg.get("model") or "").strip() or None
        self._timeout_s = float(cfg.get("timeout_s") or 30.0)
        self._max_tokens = int(cfg.get("max_tokens") or 512)
        self._max_evidence_chars = int(cfg.get("max_evidence_chars") or 2400)
        self._system_prompt = _load_prompt_file(
            str(cfg.get("system_prompt_path") or _DEFAULT_SYSTEM_PROMPT_PATH),
            _SYSTEM_PROMPT,
        )
        self._query_context_pre = _load_prompt_file(
            str(cfg.get("query_context_pre_path") or _DEFAULT_QUERY_CONTEXT_PRE_PATH),
            _QUERY_CONTEXT_PRE_FALLBACK,
        )
        self._query_context_post = _load_prompt_file(
            str(cfg.get("query_context_post_path") or _DEFAULT_QUERY_CONTEXT_POST_PATH),
            _QUERY_CONTEXT_POST_FALLBACK,
        )
        self._client: OpenAICompatClient | None = None
        self._promptops = None
        self._promptops_cfg = cfg.get("promptops", {}) if isinstance(cfg.get("promptops", {}), dict) else {}
        if bool(self._promptops_cfg.get("enabled", True)):
            try:
                from autocapture.promptops.engine import PromptOpsLayer

                self._promptops = PromptOpsLayer(
                    {
                        "promptops": self._promptops_cfg,
                        "paths": {"data_dir": str(self._promptops_cfg.get("data_dir") or "data")},
                    }
                )
            except Exception:
                self._promptops = None

    def capabilities(self) -> dict[str, Any]:
        return {"answer.synthesizer": self}

    def identity(self) -> dict[str, Any]:
        return {
            "backend": "openai_compat",
            "base_url": self._base_url,
            "model": self._model or "",
        }

    def synthesize(
        self,
        query: str,
        evidence: list[dict[str, Any]],
        *,
        max_claims: int = 3,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        q = str(query or "").strip()
        if not q:
            return {"claims": [], "error": "empty_query"}
        if self._model is None:
            return {"claims": [], "error": "model_missing"}
        if self._base_url_policy_error:
            return {"claims": [], "error": self._base_url_policy_error}
        if self._client is None:
            try:
                self._client = OpenAICompatClient(
                    base_url=self._base_url,
                    api_key=self._api_key,
                    timeout_s=self._timeout_s,
                )
            except Exception as exc:
                self._client = None
                return {"claims": [], "error": f"client_init_failed:{type(exc).__name__}:{exc}"}
        ev_lines: list[str] = []
        for item in evidence or []:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("record_id") or "").strip()
            txt = str(item.get("text") or "")
            if not rid or not txt.strip():
                continue
            ev_lines.append(f"[{rid}]\n{_truncate(txt, self._max_evidence_chars)}\n")
            if len(ev_lines) >= 16:
                break
        user_prompt_raw = (
            "Question:\n"
            f"{self._query_context_pre}\n{q}\n{self._query_context_post}\n\n"
            "Evidence snippets:\n"
            + ("\n".join(ev_lines) if ev_lines else "(none)\n")
            + "\n"
            "Return STRICT JSON with this schema:\n"
            "{"
            "\"claims\":["
            "{"
            "\"text\":\"...\","
            "\"evidence\":[{\"record_id\":\"...\",\"quote\":\"...\"}]"
            "}"
            "]"
            "}\n"
            "Rules:\n"
            "- quotes must be exact substrings from the cited record's snippet text\n"
            "- at least 1 evidence item per claim\n"
            f"- at most {int(max_claims)} claims\n"
        )
        system_prompt = self._system_prompt
        user_prompt = user_prompt_raw
        promptops_meta: dict[str, Any] = {
            "used": bool(self._promptops is not None),
            "applied": False,
            "strategy": str(self._promptops_cfg.get("model_strategy", "model_contract")),
            "query_context_injected": bool(self._query_context_pre or self._query_context_post),
            "query_context_pre_injected": bool(self._query_context_pre),
            "query_context_post_injected": bool(self._query_context_post),
        }
        if self._promptops is not None:
            try:
                strategy = str(self._promptops_cfg.get("model_strategy", "model_contract"))
                p_sys = self._promptops.prepare_prompt(
                    system_prompt,
                    prompt_id="llm.answer_synth.system",
                    strategy=strategy,
                    persist=bool(self._promptops_cfg.get("persist_prompts", False)),
                )
                p_usr = self._promptops.prepare_prompt(
                    user_prompt_raw,
                    prompt_id="llm.answer_synth.user",
                    strategy=strategy,
                    persist=bool(self._promptops_cfg.get("persist_prompts", False)),
                )
                system_prompt = p_sys.prompt
                user_prompt = p_usr.prompt
                promptops_meta["applied"] = bool(p_sys.applied or p_usr.applied)
            except Exception:
                pass
        req = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "max_tokens": int(self._max_tokens),
        }
        try:
            resp = self._client.chat_completions(req)
            choices = resp.get("choices", [])
            content = ""
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
                content = str(msg.get("content") or "").strip()
            if not content:
                if self._promptops is not None:
                    try:
                        self._promptops.record_model_interaction(
                            prompt_id="llm.answer_synth.user",
                            provider_id=self.plugin_id,
                            model=str(self._model or ""),
                            prompt_input=user_prompt_raw,
                            prompt_effective=user_prompt,
                            response_text="",
                            success=False,
                            latency_ms=float((time.perf_counter() - started) * 1000.0),
                            error="empty_completion",
                            metadata={"promptops": promptops_meta},
                        )
                    except Exception:
                        pass
                return {"claims": [], "error": "empty_completion", "model": self._model}
            try:
                parsed = json.loads(content)
            except Exception:
                # Best-effort: allow Markdown fences around JSON.
                cleaned = content.strip().strip("`").strip()
                parsed = json.loads(cleaned)
            claims = parsed.get("claims", []) if isinstance(parsed, dict) else []
            if not isinstance(claims, list):
                claims = []
            # Minimal normalization only; caller will verify quotes + citations.
            out_claims: list[dict[str, Any]] = []
            for claim in claims[: max(0, int(max_claims))]:
                if not isinstance(claim, dict):
                    continue
                text = str(claim.get("text") or "").strip()
                ev = claim.get("evidence", [])
                if not text or not isinstance(ev, list) or not ev:
                    continue
                ev_out: list[dict[str, str]] = []
                for e in ev[:4]:
                    if not isinstance(e, dict):
                        continue
                    rid = str(e.get("record_id") or "").strip()
                    quote = str(e.get("quote") or "")
                    if rid and quote:
                        ev_out.append({"record_id": rid, "quote": quote})
                if not ev_out:
                    continue
                out_claims.append({"text": text, "evidence": ev_out})
            if self._promptops is not None:
                try:
                    self._promptops.record_model_interaction(
                        prompt_id="llm.answer_synth.user",
                        provider_id=self.plugin_id,
                        model=str(self._model or ""),
                        prompt_input=user_prompt_raw,
                        prompt_effective=user_prompt,
                        response_text=content,
                        success=True,
                        latency_ms=float((time.perf_counter() - started) * 1000.0),
                        error="",
                        metadata={"promptops": promptops_meta},
                    )
                except Exception:
                    pass
            return {"claims": out_claims, "model": self._model, "backend": "openai_compat", "promptops": promptops_meta}
        except Exception as exc:
            if self._promptops is not None:
                try:
                    self._promptops.record_model_interaction(
                        prompt_id="llm.answer_synth.user",
                        provider_id=self.plugin_id,
                        model=str(self._model or ""),
                        prompt_input=user_prompt_raw,
                        prompt_effective=user_prompt,
                        response_text="",
                        success=False,
                        latency_ms=float((time.perf_counter() - started) * 1000.0),
                        error=f"synthesis_failed:{type(exc).__name__}",
                        metadata={"promptops": promptops_meta},
                    )
                except Exception:
                    pass
            return {"claims": [], "error": f"synthesis_failed:{type(exc).__name__}:{exc}", "model": self._model, "promptops": promptops_meta}


def create_plugin(plugin_id: str, context: PluginContext) -> VllmAnswerSynthesizer:
    return VllmAnswerSynthesizer(plugin_id, context)
