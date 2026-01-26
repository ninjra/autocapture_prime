"""Answer orchestrator for claim-level citations."""

from __future__ import annotations

from typing import Any

from autocapture.memory.verifier import Verifier
from autocapture.memory.conflict import detect_conflicts


class AnswerOrchestrator:
    def __init__(self) -> None:
        self._verifier = Verifier()

    def build_answer(self, claims: list[dict[str, Any]], span_ids: set[str]) -> dict[str, Any]:
        self._verifier.verify(claims, span_ids)
        conflicts = detect_conflicts(claims)
        return {"claims": claims, "conflicts": conflicts}


class LocalLLM:
    def __init__(self, model_name: str, config: dict[str, Any] | None = None) -> None:
        self.model_name = model_name
        self._pipeline = None
        self._config = config or {}

    def _load(self) -> None:
        if self._pipeline is not None:
            return
        from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

        tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        model = AutoModelForCausalLM.from_pretrained(self.model_name)
        self._pipeline = pipeline("text-generation", model=model, tokenizer=tokenizer)

    def generate(self, prompt: str, max_tokens: int = 128, *, apply_promptops: bool = True) -> str:
        if apply_promptops:
            try:
                from autocapture.promptops.engine import PromptOpsLayer

                layer = PromptOpsLayer(self._config)
                result = layer.prepare_prompt(prompt, prompt_id="llm.local")
                prompt = result.prompt
            except Exception:
                pass
        self._load()
        outputs = self._pipeline(prompt, max_new_tokens=max_tokens)
        if outputs:
            return outputs[0].get("generated_text", "")
        return ""


class LocalDecoder:
    def __init__(self, llm: LocalLLM) -> None:
        self._llm = llm

    def decode(self, prompt: str) -> str:
        return self._llm.generate(prompt)


def create_local_llm(plugin_id: str) -> LocalLLM:
    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config

    config = load_config(default_config_paths(), safe_mode=False)
    model = config.get("llm", {}).get("model", "sshleifer/tiny-gpt2")
    return LocalLLM(model, config=config)


def create_local_decoder(plugin_id: str) -> LocalDecoder:
    llm = create_local_llm(plugin_id)
    return LocalDecoder(llm)
