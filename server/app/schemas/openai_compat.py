# server/app/schemas/openai_compat.py
from __future__ import annotations

from typing import Literal, Optional
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


class DejaQDraft(BaseModel):
    """One alternative answer offered by the semantic tie-breaker.

    Two cache entries the embedding could not separate are returned together
    rather than silently coin-flipped. `label` is stable per response ("A" is
    always the one that was actually served and streamed), and `response_id` is
    what a client sends back to /v1/feedback as `chosen_draft_response_id`.
    """

    label: Literal["A", "B"]
    response_id: str
    content: str
    # The cosine distance this entry matched at. Surfaced so a client can show
    # WHY two answers were offered; nothing branches on it.
    distance: float


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
    # "length" when the token budget cut the answer off (ChatPipelineResult.
    # finish_reason, set from the generator's own done_reason/stop_reason -
    # never inferred), matching the OpenAI API's own vocabulary for this.
    finish_reason: Literal["stop", "length"] = "stop"


class OAIChatResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[OAIChoice]
    usage: OAIUsage
    # DejaQ extension, absent unless the semantic tie-breaker fired. `choices`
    # still carries the served answer on its own, so an OpenAI SDK that ignores
    # unknown keys behaves exactly as it did before this field existed.
    dejaq_drafts: Optional[list[DejaQDraft]] = None


# --- Streaming response ---

class OAIStreamDelta(BaseModel):
    role: Optional[Literal["assistant"]] = None
    content: Optional[str] = None


class OAIStreamChoice(BaseModel):
    index: int = 0
    delta: OAIStreamDelta
    finish_reason: Optional[Literal["stop", "length"]] = None


class OAIChatChunk(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[OAIStreamChoice]
    # DejaQ extension, set ONLY on the terminal chunk of a tie-broken response.
    #
    # It rides an otherwise ordinary chunk rather than a custom SSE event on
    # purpose: an OpenAI SDK parses every `data:` line into a
    # ChatCompletionChunk, and an event carrying a foreign shape (no `choices`)
    # fails that validation and breaks the client. An extra top-level key on a
    # legal chunk is ignored by every SDK, so this is the only
    # backwards-compatible channel available. Emitted with exclude_none so it
    # never appears as `"dejaq_drafts": null` on the ordinary chunks.
    dejaq_drafts: Optional[list[DejaQDraft]] = None
