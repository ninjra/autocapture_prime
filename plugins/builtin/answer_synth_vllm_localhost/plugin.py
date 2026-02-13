"""Citation-friendly answer synthesizer via a localhost OpenAI-compatible LLM.

The synthesizer must not fabricate evidence. It returns claims with explicit
quotes tied to record_ids so the kernel can build verifiable citations.
"""

from __future__ import annotations

import json
from typing import Any

from autocapture_nx.inference.openai_compat import OpenAICompatClient
from autocapture_nx.inference.vllm_endpoint import EXTERNAL_VLLM_BASE_URL, enforce_external_vllm_base_url
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


_SYSTEM_PROMPT = (
    "You are a careful assistant answering questions about a user's computer activity. "
    "You MUST use only the provided evidence snippets. "
    "Every claim MUST be backed by at least one exact quote that appears verbatim in an evidence snippet. "
    "If you cannot answer from evidence, return an empty claims list."
)


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
        self._client: OpenAICompatClient | None = None

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
        user_prompt = (
            "Question:\n"
            f"{q}\n\n"
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
        req = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
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
            return {"claims": out_claims, "model": self._model, "backend": "openai_compat"}
        except Exception as exc:
            return {"claims": [], "error": f"synthesis_failed:{type(exc).__name__}:{exc}", "model": self._model}


def create_plugin(plugin_id: str, context: PluginContext) -> VllmAnswerSynthesizer:
    return VllmAnswerSynthesizer(plugin_id, context)
