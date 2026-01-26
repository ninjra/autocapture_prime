"""Egress sanitization plugin."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from typing import Any

from autocapture_nx.kernel.crypto import derive_key
from autocapture_nx.kernel.keyring import KeyRing
from autocapture_nx.plugin_system.api import PluginBase, PluginContext


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
URL_RE = re.compile(r"\bhttps?://[^\s]+\b")
FILEPATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s]+\b")
NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")
TOKEN_RE = re.compile(r"⟦ENT:([A-Z_]+):([A-Z2-7]+)⟧")


@dataclass
class Entity:
    start: int
    end: int
    kind: str
    value: str


class EntityMap:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, str]] = {}

    def put(self, token: str, value: str, kind: str) -> None:
        self._data[token] = {"value": value, "kind": kind}

    def get(self, token: str) -> dict[str, str] | None:
        return self._data.get(token)

    def items(self) -> dict[str, dict[str, str]]:
        return dict(self._data)


class EgressSanitizer(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._entity_map = None
        self._entity_key = None

    def capabilities(self) -> dict[str, Any]:
        return {"privacy.egress_sanitizer": self}

    def _get_entity_map(self) -> EntityMap:
        if self._entity_map is not None:
            return self._entity_map
        try:
            store = self.context.get_capability("storage.entity_map")
            self._entity_map = store
        except Exception:
            self._entity_map = EntityMap()
        return self._entity_map

    def _entity_key_bytes(self) -> bytes:
        if self._entity_key is not None:
            return self._entity_key
        storage_cfg = self.context.config.get("storage", {})
        crypto_cfg = storage_cfg.get("crypto", {})
        root_key_path = crypto_cfg.get("root_key_path", "data/vault/root.key")
        keyring_path = crypto_cfg.get("keyring_path", "data/vault/keyring.json")
        encryption_required = storage_cfg.get("encryption_required", False)
        require_protection = bool(encryption_required and os.name == "nt")
        keyring = KeyRing.load(keyring_path, legacy_root_path=root_key_path, require_protection=require_protection)
        _key_id, root = keyring.active_key()
        self._entity_key = derive_key(root, "entity_tokens")
        return self._entity_key

    def _token_for(self, value: str, kind: str, scope: str) -> str:
        key = self._entity_key_bytes()
        msg = f"{value}|{kind}|{scope}".encode("utf-8")
        digest = hmac.new(key, msg, hashlib.sha256).digest()
        length = 16
        token = None
        entity_map = self._get_entity_map()
        while token is None:
            candidate = base64.b32encode(digest[:length]).decode("ascii").rstrip("=")
            existing = entity_map.get(candidate)
            if existing and existing.get("value") != value:
                length += 4
                continue
            token = candidate
        return token

    def _token_format(self, kind: str, token: str) -> str:
        fmt = self.context.config.get("privacy", {}).get("egress", {}).get("token_format", "⟦ENT:{type}:{token}⟧")
        return fmt.format(type=kind, token=token)

    def _recognizers(self) -> list[tuple[str, re.Pattern[str]]]:
        rec = self.context.config.get("privacy", {}).get("egress", {}).get("recognizers", {})
        recognizers = []
        if rec.get("ssn", True):
            recognizers.append(("SSN", SSN_RE))
        if rec.get("credit_card", True):
            recognizers.append(("CREDIT_CARD", CREDIT_CARD_RE))
        if rec.get("email", True):
            recognizers.append(("EMAIL", EMAIL_RE))
        if rec.get("phone", True):
            recognizers.append(("PHONE", PHONE_RE))
        if rec.get("ipv4", True):
            recognizers.append(("IPV4", IPV4_RE))
        if rec.get("url", True):
            recognizers.append(("URL", URL_RE))
        if rec.get("filepath", True):
            recognizers.append(("FILEPATH", FILEPATH_RE))
        if rec.get("names", True):
            recognizers.append(("NAME", NAME_RE))
        for regex in rec.get("custom_regex", []) or []:
            recognizers.append(("CUSTOM", re.compile(regex)))
        return recognizers

    def _find_entities(self, text: str) -> list[Entity]:
        matches: list[Entity] = []
        for kind, pattern in self._recognizers():
            for match in pattern.finditer(text):
                matches.append(Entity(match.start(), match.end(), kind, match.group(0)))
        matches.sort(key=lambda m: (m.start, -(m.end - m.start), m.kind))
        selected: list[Entity] = []
        last_end = -1
        for ent in matches:
            if ent.start < last_end:
                continue
            selected.append(ent)
            last_end = ent.end
        return selected

    def sanitize_text(self, text: str, scope: str = "default") -> dict[str, Any]:
        entities = self._find_entities(text)
        if not entities:
            return {"text": text, "glossary": [], "tokens": {}}
        entity_map = self._get_entity_map()
        output = []
        cursor = 0
        tokens: dict[str, dict[str, str]] = {}
        glossary: list[dict[str, str]] = []
        for ent in entities:
            output.append(text[cursor:ent.start])
            token = self._token_for(ent.value, ent.kind, scope)
            token_str = self._token_format(ent.kind, token)
            output.append(token_str)
            cursor = ent.end
            entity_map.put(token, ent.value, ent.kind)
            tokens[token] = {"value": ent.value, "kind": ent.kind}
            glossary.append({"token": token, "kind": ent.kind})
        output.append(text[cursor:])
        return {"text": "".join(output), "glossary": glossary, "tokens": tokens}

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

    def _collect_strings(self, value: Any, out: list[str]) -> None:
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, list):
            for item in value:
                self._collect_strings(item, out)
        elif isinstance(value, dict):
            for item in value.values():
                self._collect_strings(item, out)

    def leak_check(self, sanitized: dict[str, Any]) -> bool:
        tokens = sanitized.get("_tokens", {})
        haystack: list[str] = []
        filtered = {k: v for k, v in sanitized.items() if k not in ("_tokens", "_glossary")}
        self._collect_strings(filtered, haystack)
        for token_data in tokens.values():
            value = token_data.get("value")
            if not value:
                continue
            if any(value in s for s in haystack):
                return False
        return True

    def detokenize_text(self, text: str) -> str:
        entity_map = self._get_entity_map()
        def repl(match: re.Match[str]) -> str:
            token = match.group(2)
            data = entity_map.get(token)
            if not data:
                return match.group(0)
            return data.get("value", match.group(0))
        return TOKEN_RE.sub(repl, text)

    def detokenize_payload(self, payload: Any) -> Any:
        if isinstance(payload, str):
            return self.detokenize_text(payload)
        if isinstance(payload, list):
            return [self.detokenize_payload(v) for v in payload]
        if isinstance(payload, dict):
            return {k: self.detokenize_payload(v) for k, v in payload.items()}
        return payload


def create_plugin(plugin_id: str, context: PluginContext) -> EgressSanitizer:
    return EgressSanitizer(plugin_id, context)
