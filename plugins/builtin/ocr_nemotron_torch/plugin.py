"""Nemotron OCR plugin with fail-closed local+localhost execution paths.

Backend order:
1) Local torch/transformers model when model_id is configured.
2) Localhost-only OpenAI-compatible endpoint (for example vLLM) as fallback.
3) Fail closed with explicit error details.
"""

from __future__ import annotations

from io import BytesIO
import time
from typing import Any

from autocapture_nx.inference.openai_compat import OpenAICompatClient, image_bytes_to_data_url
from autocapture_nx.inference.vllm_endpoint import EXTERNAL_VLLM_BASE_URL, enforce_external_vllm_base_url
from autocapture_nx.plugin_system.api import PluginBase, PluginContext

try:  # pragma: no cover - optional dependency guard
    from PIL import Image

    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency guard
    Image = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False


_DEFAULT_OCR_PROMPT = (
    "Extract visible on-screen text exactly as shown. "
    "Return plain text only. Do not add commentary."
)


class NemotronOCR(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        self._model_id = str(cfg.get("model_id") or "").strip()
        self._device = str(cfg.get("device") or "cuda").strip()
        self._base_url_policy_error = ""
        try:
            self._base_url = enforce_external_vllm_base_url(cfg.get("base_url"))
        except Exception as exc:
            self._base_url = EXTERNAL_VLLM_BASE_URL
            self._base_url_policy_error = f"invalid_vllm_base_url:{type(exc).__name__}:{exc}"
        self._api_key = str(cfg.get("api_key") or "").strip() or None
        self._timeout_s = float(cfg.get("timeout_s") or 25.0)
        self._max_tokens = int(cfg.get("max_tokens") or 384)
        self._prompt = str(cfg.get("prompt") or _DEFAULT_OCR_PROMPT).strip() or _DEFAULT_OCR_PROMPT
        self._client: OpenAICompatClient | None = None
        self._openai_model: str | None = None
        self._torch_loaded = False
        self._torch = None
        self._processor = None
        self._model = None
        self._local_error = ""
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
        return {"ocr.engine": self}

    def extract(self, frame_bytes: bytes) -> dict[str, Any]:
        if not frame_bytes:
            return {"text": "", "engine": "nemotron", "model_id": self._model_id, "backend": "unavailable", "error": "empty_frame"}

        errors: list[str] = []

        local = self._extract_local_torch(frame_bytes)
        if local.get("text"):
            return local
        if local.get("error"):
            errors.append(str(local.get("error")))

        compat = self._extract_openai_compat(frame_bytes)
        if compat.get("text"):
            return compat
        if compat.get("error"):
            errors.append(str(compat.get("error")))

        error_blob = ";".join([item for item in errors if item]) or "ocr_unavailable"
        return {
            "text": "",
            "engine": "nemotron",
            "model_id": self._model_id,
            "backend": "unavailable",
            "error": error_blob,
        }

    def _extract_local_torch(self, frame_bytes: bytes) -> dict[str, Any]:
        started = time.perf_counter()
        out = {"text": "", "engine": "nemotron", "model_id": self._model_id, "backend": "nemotron_torch_local"}
        if not self._model_id:
            out["error"] = "model_id_missing"
            return out
        if not _PIL_AVAILABLE:
            out["error"] = "pil_missing"
            return out
        self._ensure_local_model()
        if self._model is None or self._processor is None or self._torch is None:
            out["error"] = self._local_error or "local_model_unavailable"
            return out
        try:
            image = Image.open(BytesIO(frame_bytes)).convert("RGB")  # type: ignore[arg-type]
        except Exception as exc:
            out["error"] = f"image_decode_failed:{type(exc).__name__}"
            return out
        try:
            prompt_effective, prompt_meta = self._prepare_promptops_prompt(
                self._prompt,
                prompt_id="llm.ocr.local",
                fallback_strategy="model_contract",
            )
            messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt_effective}]}]
            prompt = self._processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = self._processor(text=[prompt], images=[image], return_tensors="pt")
            model_device = getattr(self._model, "device", None)
            if model_device is not None:
                try:
                    inputs = inputs.to(model_device)
                except Exception:
                    pass
            with self._torch.no_grad():
                output_ids = self._model.generate(
                    **inputs,
                    max_new_tokens=self._max_tokens,
                    do_sample=False,
                )
            prompt_len = int(inputs.input_ids.shape[1]) if hasattr(inputs, "input_ids") else 0
            trimmed = [output_ids[i][prompt_len:] for i in range(int(output_ids.shape[0]))]
            decoded = self._processor.batch_decode(
                trimmed,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )
            text = str(decoded[0] if decoded else "").strip()
            out["text"] = text
            if not text:
                out["error"] = "local_empty_response"
            self._record_promptops_interaction(
                prompt_id="llm.ocr.local",
                prompt_input=self._prompt,
                prompt_effective=prompt_effective,
                response_text=text,
                success=bool(text),
                latency_ms=float((time.perf_counter() - started) * 1000.0),
                error=str(out.get("error") or ""),
                metadata={"backend": "local_torch", "promptops": prompt_meta},
            )
            return out
        except Exception as exc:
            out["error"] = f"local_inference_failed:{type(exc).__name__}"
            self._record_promptops_interaction(
                prompt_id="llm.ocr.local",
                prompt_input=self._prompt,
                prompt_effective=self._prompt,
                response_text="",
                success=False,
                latency_ms=float((time.perf_counter() - started) * 1000.0),
                error=str(out.get("error") or ""),
                metadata={"backend": "local_torch"},
            )
            return out

    def _ensure_local_model(self) -> None:
        if self._torch_loaded:
            return
        self._torch_loaded = True
        try:
            import torch
            from transformers import AutoModelForVision2Seq, AutoProcessor

            model = AutoModelForVision2Seq.from_pretrained(
                self._model_id,
                local_files_only=True,
                torch_dtype=getattr(torch, "float16", None) if bool(getattr(torch.cuda, "is_available", lambda: False)()) else "auto",
            )
            processor = AutoProcessor.from_pretrained(
                self._model_id,
                local_files_only=True,
            )
            model.eval()
            if self._device and self._device.startswith("cuda") and bool(getattr(torch.cuda, "is_available", lambda: False)()):
                try:
                    model = model.to(self._device)
                except Exception:
                    pass
            try:
                torch.set_grad_enabled(False)
                torch.manual_seed(0)
                if hasattr(torch, "use_deterministic_algorithms"):
                    torch.use_deterministic_algorithms(True)
            except Exception:
                pass
            self._torch = torch
            self._processor = processor
            self._model = model
            self._local_error = ""
        except Exception as exc:
            self._local_error = f"local_model_load_failed:{type(exc).__name__}"
            self._torch = None
            self._processor = None
            self._model = None

    def _extract_openai_compat(self, frame_bytes: bytes) -> dict[str, Any]:
        started = time.perf_counter()
        out = {"text": "", "engine": "nemotron", "model_id": self._openai_model or "", "backend": "openai_compat_ocr"}
        client = self._ensure_client()
        if client is None:
            out["error"] = self._base_url_policy_error or "openai_client_unavailable"
            return out
        model = self._openai_model
        if not model:
            model = self._discover_model(client)
            self._openai_model = model
        if not model:
            out["error"] = "openai_model_missing"
            return out
        prompt_effective, prompt_meta = self._prepare_promptops_prompt(
            self._prompt,
            prompt_id="llm.ocr.openai_compat",
            fallback_strategy="model_contract",
        )
        request = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_effective},
                        {"type": "image_url", "image_url": {"url": image_bytes_to_data_url(frame_bytes, content_type="image/png")}},
                    ],
                }
            ],
            "temperature": 0,
            "max_tokens": int(self._max_tokens),
        }
        try:
            response = client.chat_completions(request)
        except Exception as exc:
            out["error"] = f"openai_request_failed:{type(exc).__name__}"
            self._record_promptops_interaction(
                prompt_id="llm.ocr.openai_compat",
                prompt_input=self._prompt,
                prompt_effective=prompt_effective,
                response_text="",
                success=False,
                latency_ms=float((time.perf_counter() - started) * 1000.0),
                error=str(out.get("error") or ""),
                metadata={"backend": "openai_compat", "promptops": prompt_meta},
            )
            return out
        choices = response.get("choices", []) if isinstance(response, dict) else []
        if not isinstance(choices, list) or not choices:
            out["error"] = "openai_empty_choices"
            self._record_promptops_interaction(
                prompt_id="llm.ocr.openai_compat",
                prompt_input=self._prompt,
                prompt_effective=prompt_effective,
                response_text="",
                success=False,
                latency_ms=float((time.perf_counter() - started) * 1000.0),
                error=str(out.get("error") or ""),
                metadata={"backend": "openai_compat", "promptops": prompt_meta},
            )
            return out
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        text = str(message.get("content") or "").strip()
        out["text"] = text
        out["model_id"] = str(model)
        if not text:
            out["error"] = "openai_empty_response"
        self._record_promptops_interaction(
            prompt_id="llm.ocr.openai_compat",
            prompt_input=self._prompt,
            prompt_effective=prompt_effective,
            response_text=text,
            success=bool(text),
            latency_ms=float((time.perf_counter() - started) * 1000.0),
            error=str(out.get("error") or ""),
            metadata={"backend": "openai_compat", "promptops": prompt_meta},
        )
        return out

    def _prepare_promptops_prompt(self, prompt: str, *, prompt_id: str, fallback_strategy: str) -> tuple[str, dict[str, Any]]:
        meta: dict[str, Any] = {
            "used": bool(self._promptops is not None),
            "applied": False,
            "strategy": str(self._promptops_cfg.get("model_strategy", fallback_strategy)),
        }
        if self._promptops is None:
            return str(prompt or ""), meta
        try:
            strategy = str(self._promptops_cfg.get("model_strategy", fallback_strategy))
            result = self._promptops.prepare_prompt(
                str(prompt or ""),
                prompt_id=str(prompt_id),
                strategy=strategy,
                persist=bool(self._promptops_cfg.get("persist_prompts", False)),
            )
            meta["applied"] = bool(result.applied)
            return str(result.prompt or ""), meta
        except Exception:
            return str(prompt or ""), meta

    def _record_promptops_interaction(
        self,
        *,
        prompt_id: str,
        prompt_input: str,
        prompt_effective: str,
        response_text: str,
        success: bool,
        latency_ms: float,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._promptops is None:
            return
        try:
            self._promptops.record_model_interaction(
                prompt_id=str(prompt_id),
                provider_id=self.plugin_id,
                model=str(self._openai_model or self._model_id or ""),
                prompt_input=str(prompt_input or ""),
                prompt_effective=str(prompt_effective or ""),
                response_text=str(response_text or ""),
                success=bool(success),
                latency_ms=float(latency_ms),
                error=str(error or ""),
                metadata=metadata if isinstance(metadata, dict) else {},
            )
        except Exception:
            return

    def _ensure_client(self) -> OpenAICompatClient | None:
        if self._client is not None:
            return self._client
        if self._base_url_policy_error:
            return None
        try:
            self._client = OpenAICompatClient(
                base_url=self._base_url,
                api_key=self._api_key,
                timeout_s=self._timeout_s,
            )
        except Exception:
            self._client = None
        return self._client

    @staticmethod
    def _discover_model(client: OpenAICompatClient) -> str | None:
        try:
            payload = client.list_models()
        except Exception:
            return None
        data = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(data, list):
            return None
        for item in data:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if model_id:
                return model_id
        return None


def create_plugin(plugin_id: str, context: PluginContext) -> NemotronOCR:
    return NemotronOCR(plugin_id, context)
