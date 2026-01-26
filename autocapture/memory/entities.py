"""Deterministic entity hashing for egress sanitization."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass

from autocapture_nx.kernel.crypto import derive_key
from autocapture_nx.kernel.keyring import KeyRing


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
URL_RE = re.compile(r"\bhttps?://[^\s]+\b")
FILEPATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s]+\b")
NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")


@dataclass(frozen=True)
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

    def tokens(self) -> dict[str, dict[str, str]]:
        return dict(self._data)


class EntityHasher:
    def __init__(self, key: bytes, token_format: str) -> None:
        self._key = key
        self._token_format = token_format

    def _token_for(self, value: str, kind: str, scope: str, existing: EntityMap) -> str:
        msg = f"{value}|{kind}|{scope}".encode("utf-8")
        digest = hmac.new(self._key, msg, hashlib.sha256).digest()
        length = 16
        while True:
            candidate = base64.b32encode(digest[:length]).decode("ascii").rstrip("=")
            found = existing.get(candidate)
            if found and found.get("value") != value:
                length += 4
                continue
            return candidate

    def sanitize_text(self, text: str, scope: str, entity_map: EntityMap, config: dict) -> tuple[str, dict[str, dict[str, str]]]:
        entities = _find_entities(text, config)
        if not entities:
            return text, {}
        output = []
        cursor = 0
        tokens: dict[str, dict[str, str]] = {}
        for ent in entities:
            output.append(text[cursor:ent.start])
            token = self._token_for(ent.value, ent.kind, scope, entity_map)
            token_str = self._token_format.format(type=ent.kind, token=token)
            output.append(token_str)
            cursor = ent.end
            entity_map.put(token, ent.value, ent.kind)
            tokens[token] = {"value": ent.value, "kind": ent.kind}
        output.append(text[cursor:])
        return "".join(output), tokens


def _recognizers(config: dict) -> list[tuple[str, re.Pattern[str]]]:
    rec = config.get("privacy", {}).get("egress", {}).get("recognizers", {})
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
        try:
            recognizers.append(("CUSTOM", re.compile(regex)))
        except re.error:
            continue
    return recognizers


def _find_entities(text: str, config: dict) -> list[Entity]:
    matches: list[Entity] = []
    for kind, pattern in _recognizers(config):
        for m in pattern.finditer(text):
            matches.append(Entity(start=m.start(), end=m.end(), kind=kind, value=m.group(0)))
    matches.sort(key=lambda e: (e.start, e.end - e.start), reverse=False)
    selected: list[Entity] = []
    last_end = -1
    for ent in matches:
        if ent.start < last_end:
            continue
        selected.append(ent)
        last_end = ent.end
    return selected


def build_hasher(config: dict) -> tuple[EntityHasher, EntityMap]:
    storage_cfg = config.get("storage", {})
    crypto_cfg = storage_cfg.get("crypto", {})
    root_key_path = crypto_cfg.get("root_key_path", "data/vault/root.key")
    keyring_path = crypto_cfg.get("keyring_path", "data/vault/keyring.json")
    keyring = KeyRing.load(keyring_path, legacy_root_path=root_key_path)
    _key_id, root = keyring.active_key()
    key = derive_key(root, "entity_tokens")
    token_format = config.get("privacy", {}).get("egress", {}).get("token_format", "⟦ENT:{type}:{token}⟧")
    return EntityHasher(key, token_format), EntityMap()
