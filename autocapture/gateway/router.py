"""Gateway router."""

from __future__ import annotations

import time
from fastapi import APIRouter, HTTPException

from autocapture.config.defaults import default_config_paths
from autocapture.config.load import load_config
from autocapture.gateway.schemas import ChatRequest, ChatResponse, ChatChoice, ChatMessage
from autocapture.memory.answer_orchestrator import create_local_llm
from autocapture.promptops.engine import PromptOpsLayer
from autocapture.plugins.policy_gate import PolicyGate
from autocapture.ux.redaction import EgressSanitizer
from autocapture.core.http import EgressClient

router = APIRouter()


def _config():
    return load_config(default_config_paths(), safe_mode=False)


@router.post("/v1/chat/completions", response_model=ChatResponse)
def chat(req: ChatRequest):
    config = _config()
    prompt = "\n".join([m.content for m in req.messages])
    promptops = PromptOpsLayer(config)
    prepared = promptops.prepare_prompt(prompt, prompt_id="gateway.chat")
    prepared_prompt = prepared.prompt

    if req.use_cloud:
        sanitizer = EgressSanitizer(config)
        gate = PolicyGate(config, sanitizer)
        payload = req.model_dump()
        payload["messages"] = [{"role": "user", "content": prepared_prompt}]
        base_url = config.get("gateway", {}).get("openai_base_url")
        if not base_url:
            raise HTTPException(status_code=400, detail="gateway_base_url_missing")
        decision = gate.enforce("mx.core.llm_openai_compat", payload, url=str(base_url))
        if not decision.ok:
            raise HTTPException(status_code=403, detail=decision.reason)
        client = EgressClient(gate)
        try:
            resp = client.post(
                f"{base_url}/v1/chat/completions",
                plugin_id="mx.core.llm_openai_compat",
                payload=payload,
            )
        except Exception as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        data = resp.json()
        message = data.get("choices", [{}])[0].get("message", {})
        content = message.get("content", "")
    else:
        llm = create_local_llm("mx.core.llm_local")
        content = llm.generate(prepared_prompt, apply_promptops=False)

    choice = ChatChoice(index=0, message=ChatMessage(role="assistant", content=content))
    return ChatResponse(id="chatcmpl-local", object="chat.completion", created=int(time.time()), choices=[choice])


def create_openai_provider(plugin_id: str):
    return chat
