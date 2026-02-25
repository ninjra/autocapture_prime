"""Stable PromptOps contract API for internal/external callers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autocapture.promptops.propose import propose_prompt
from autocapture.promptops.service import get_promptops_layer


@dataclass(frozen=True)
class PromptPrepared:
    prompt: str
    prompt_id: str
    applied: bool
    strategy: str
    trace: dict[str, Any]


class PromptOpsAPI:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config if isinstance(config, dict) else {}
        self._layer = get_promptops_layer(self._config)

    def _resolve_prompt_id(self, task_class: str, context: dict[str, Any] | None = None) -> str:
        ctx = context if isinstance(context, dict) else {}
        explicit = str(ctx.get("prompt_id") or "").strip()
        if explicit:
            return explicit
        clean = str(task_class or "").strip().lower().replace(" ", "_")
        if clean in {"query", "query.default"}:
            return "query.default"
        if clean in {"state_query", "state.query"}:
            return "state_query"
        if clean:
            return clean
        return "default"

    def prepare(self, task_class: str, raw_prompt: str, context: dict[str, Any] | None = None) -> PromptPrepared:
        ctx = context if isinstance(context, dict) else {}
        prompt_id = self._resolve_prompt_id(task_class, ctx)
        if "sources" in ctx:
            raw_sources = ctx.get("sources")
            sources = raw_sources if isinstance(raw_sources, list) else []
        else:
            # Omitted sources means "use promptops.sources from config".
            sources = None
        strategy = str(ctx.get("strategy") or "").strip().lower()
        if task_class in {"query", "query.default", "state_query", "state.query"}:
            result = self._layer.prepare_query(str(raw_prompt or ""), prompt_id=prompt_id, sources=sources)
            strategy_out = str(result.trace.get("strategy") if isinstance(result.trace, dict) else "none")
            return PromptPrepared(
                prompt=result.prompt,
                prompt_id=prompt_id,
                applied=bool(result.applied),
                strategy=strategy_out,
                trace=result.trace if isinstance(result.trace, dict) else {},
            )
        result = self._layer.prepare_prompt(
            str(raw_prompt or ""),
            prompt_id=prompt_id,
            sources=sources,
            strategy=(strategy or None),
            persist=(bool(ctx.get("persist_prompts")) if "persist_prompts" in ctx else None),
        )
        strategy_out = str(result.trace.get("strategy") if isinstance(result.trace, dict) else (strategy or "none"))
        return PromptPrepared(
            prompt=result.prompt,
            prompt_id=prompt_id,
            applied=bool(result.applied),
            strategy=strategy_out,
            trace=result.trace if isinstance(result.trace, dict) else {},
        )

    def record_outcome(
        self,
        *,
        task_class: str,
        prompt_input: str,
        prompt_effective: str,
        response_text: str,
        success: bool,
        latency_ms: float,
        provider_id: str,
        model: str,
        error: str = "",
        metadata: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        allow_review: bool = True,
    ) -> dict[str, Any]:
        prompt_id = self._resolve_prompt_id(task_class, context)
        return self._layer.record_model_interaction(
            prompt_id=prompt_id,
            provider_id=str(provider_id or ""),
            model=str(model or ""),
            prompt_input=str(prompt_input or ""),
            prompt_effective=str(prompt_effective or ""),
            response_text=str(response_text or ""),
            success=bool(success),
            latency_ms=float(latency_ms),
            error=str(error or ""),
            metadata=metadata if isinstance(metadata, dict) else None,
            allow_review=bool(allow_review),
        )

    def recommend_template(self, task_class: str, raw_prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        prompt_id = self._resolve_prompt_id(task_class, context)
        stored = self._layer._store.get(prompt_id)  # noqa: SLF001
        if stored:
            return {
                "prompt_id": prompt_id,
                "source": "stored_prompt",
                "recommended_prompt": stored,
            }
        strategy = "normalize_query" if "query" in prompt_id else "model_contract"
        proposal = propose_prompt(str(raw_prompt or ""), {"sources": []}, strategy=strategy)
        return {
            "prompt_id": prompt_id,
            "source": "generated_candidate",
            "strategy": strategy,
            "recommended_prompt": str(proposal.get("proposal") or raw_prompt or ""),
        }
