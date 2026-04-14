# server/app/schemas/openai_compat.py
from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict


class OAIMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: str


class OAIChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[OAIMessage]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


# --- Non-streaming response ---

class OAIUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class OAIMessageResponse(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class OAIChoice(BaseModel):
    index: int = 0
    message: OAIMessageResponse
    finish_reason: Literal["stop"] = "stop"


class OAIChatResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[OAIChoice]
    usage: OAIUsage


# --- Streaming response ---

class OAIStreamDelta(BaseModel):
    role: Optional[Literal["assistant"]] = None
    content: Optional[str] = None


class OAIStreamChoice(BaseModel):
    index: int = 0
    delta: OAIStreamDelta
    finish_reason: Optional[Literal["stop"]] = None


class OAIChatChunk(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[OAIStreamChoice]
