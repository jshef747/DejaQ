from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator


class OAIResponsesContentPart(BaseModel):
    type: Literal["input_text", "input_image", "output_text"]
    text: Optional[str] = None
    image_url: Optional[str] = None


class OAIResponsesInputItem(BaseModel):
    role: str
    content: Union[str, list[OAIResponsesContentPart]]


class OAIResponsesRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    input: Union[str, list[OAIResponsesInputItem]]
    instructions: Optional[str] = None
    stream: bool = False
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def reject_server_state_fields(cls, values: dict) -> dict:
        for field in ("previous_response_id", "conversation"):
            if values.get(field) is not None:
                raise ValueError(
                    f"'{field}' is not supported — DejaQ is stateless. "
                    "Send the full conversation history in 'input' on each request."
                )
        return values


# --- Non-streaming response shapes ---

class OAIResponseUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class OAIResponseContentPart(BaseModel):
    type: Literal["output_text"] = "output_text"
    text: str


class OAIResponseOutputMessage(BaseModel):
    id: str
    type: Literal["message"] = "message"
    role: Literal["assistant"] = "assistant"
    content: list[OAIResponseContentPart]
    status: Literal["completed"] = "completed"


class OAIResponse(BaseModel):
    id: str
    object: Literal["response"] = "response"
    created_at: int
    model: str
    status: Literal["completed"] = "completed"
    output: list[OAIResponseOutputMessage]
    output_text: str
    usage: OAIResponseUsage


# --- Streaming event shapes ---

class ResponseCreatedEvent(BaseModel):
    type: Literal["response.created"] = "response.created"
    response: dict


class ResponseOutputItemAddedEvent(BaseModel):
    type: Literal["response.output_item.added"] = "response.output_item.added"
    output_index: int = 0
    item: dict


class ResponseContentPartAddedEvent(BaseModel):
    type: Literal["response.content_part.added"] = "response.content_part.added"
    item_id: str
    output_index: int = 0
    content_index: int = 0
    part: dict


class ResponseOutputTextDeltaEvent(BaseModel):
    type: Literal["response.output_text.delta"] = "response.output_text.delta"
    item_id: str
    output_index: int = 0
    content_index: int = 0
    delta: str


class ResponseOutputTextDoneEvent(BaseModel):
    type: Literal["response.output_text.done"] = "response.output_text.done"
    item_id: str
    output_index: int = 0
    content_index: int = 0
    text: str


class ResponseContentPartDoneEvent(BaseModel):
    type: Literal["response.content_part.done"] = "response.content_part.done"
    item_id: str
    output_index: int = 0
    content_index: int = 0
    part: dict


class ResponseOutputItemDoneEvent(BaseModel):
    type: Literal["response.output_item.done"] = "response.output_item.done"
    output_index: int = 0
    item: dict


class ResponseCompletedEvent(BaseModel):
    type: Literal["response.completed"] = "response.completed"
    response: dict
