"""Redaction and egress sanitization utilities."""

from __future__ import annotations

from typing import Any

from autocapture.memory.entities import build_hasher


class EgressSanitizer:
    def __init__(self, config: dict) -> None:
        self._config = config
        self._hasher, self._entity_map = build_hasher(config)

    def sanitize_text(self, text: str, scope: str = "default") -> dict[str, Any]:
        sanitized, tokens = self._hasher.sanitize_text(text, scope, self._entity_map, self._config)
        glossary = [{"token": token, "kind": meta["kind"]} for token, meta in tokens.items()]
        return {"text": sanitized, "tokens": tokens, "glossary": glossary}

    def _sanitize_value(self, value: Any, scope: str, glossary: list[dict[str, str]], tokens: dict[str, dict[str, str]]) -> Any:
        if isinstance(value, str):
            result = self.sanitize_text(value, scope=scope)
            glossary.extend(result["glossary"])
            tokens.update(result["tokens"])
            return result["text"]
        if isinstance(value, list):
            return [self._sanitize_value(v, scope, glossary, tokens) for v in value]
        if isinstance(value, dict):
            return {k: self._sanitize_value(v, scope, glossary, tokens) for k, v in value.items()}
        return value

    def sanitize_payload(self, payload: dict[str, Any], scope: str = "default") -> dict[str, Any]:
        glossary: list[dict[str, str]] = []
        tokens: dict[str, dict[str, str]] = {}
        sanitized = self._sanitize_value(payload, scope, glossary, tokens)
        if isinstance(sanitized, dict):
            sanitized["_glossary"] = glossary
            sanitized["_tokens"] = tokens
            return sanitized
        return {"payload": sanitized, "_glossary": glossary, "_tokens": tokens}

    def leak_check(self, sanitized: dict[str, Any]) -> bool:
        tokens = sanitized.get("_tokens", {})
        haystack: list[str] = []

        def collect(value: Any) -> None:
            if isinstance(value, str):
                haystack.append(value)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
            elif isinstance(value, dict):
                for item in value.values():
                    collect(item)

        filtered = {k: v for k, v in sanitized.items() if k not in ("_tokens", "_glossary")}
        collect(filtered)
        for token_data in tokens.values():
            value = token_data.get("value")
            if not value:
                continue
            if any(value in s for s in haystack):
                return False
        return True

    def detokenize_text(self, text: str) -> str:
        for token, meta in self._entity_map.tokens().items():
            text = text.replace(self._config.get("privacy", {}).get("egress", {}).get("token_format", "⟦ENT:{type}:{token}⟧").format(type=meta["kind"], token=token), meta["value"])
        return text

    def detokenize_payload(self, payload: Any) -> Any:
        if isinstance(payload, str):
            return self.detokenize_text(payload)
        if isinstance(payload, list):
            return [self.detokenize_payload(v) for v in payload]
        if isinstance(payload, dict):
            return {k: self.detokenize_payload(v) for k, v in payload.items()}
        return payload

    def redact_image(self, image, placeholder: str = "[REDACTED]"):
        from PIL import ImageDraw
        try:
            import pytesseract
        except Exception as exc:
            raise RuntimeError(f"OCR unavailable for redaction: {exc}")
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        draw = ImageDraw.Draw(image)
        for i, text in enumerate(data.get("text", [])):
            if not text:
                continue
            x = int(data["left"][i])
            y = int(data["top"][i])
            w = int(data["width"][i])
            h = int(data["height"][i])
            draw.rectangle([x, y, x + w, y + h], fill="black")
            draw.text((x, y), placeholder, fill="white")
        return image


def create_egress_sanitizer(plugin_id: str) -> EgressSanitizer:
    from autocapture.config.defaults import default_config_paths
    from autocapture.config.load import load_config

    config = load_config(default_config_paths(), safe_mode=False)
    return EgressSanitizer(config)
