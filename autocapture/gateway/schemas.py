"""Gateway schemas."""

from __future__ import annotations

from pydantic import BaseModel
from typing import List


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str | None = None
    messages: List[ChatMessage]
    use_cloud: bool = False


class ChatChoice(BaseModel):
    index: int
    message: ChatMessage


class ChatResponse(BaseModel):
    id: str
    object: str
    created: int
    choices: List[ChatChoice]
