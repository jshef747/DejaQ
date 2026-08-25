from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator

# One shape for both gateways: a client that speaks either API gets the same
# draft object, and there is only one place to change it.
from app.schemas.openai_compat import DejaQDraft


class OAIResponsesContentPart(BaseModel):
    type: Literal["input_text", "input_image", "input_file", "output_text"]
    text: Optional[str] = None
    image_url: Optional[str] = None
    # input_file, matching OpenAI's shape. `file_data` is a data: URL, same as
    # image_url — DejaQ takes no remote URLs and no file ids.
    filename: Optional[str] = None
    file_data: Optional[str] = None


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
    # Explicit `@`-reference to one knowledge-base document (its catalog id).
    # When set, retrieval fetches THAT document's own chunks by id instead of
    # running the normal nearest-neighbour search — see openai_compat.py.
    rag_document_id: Optional[int] = None

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
    # "incomplete" when the token budget cut the answer off (see
    # ChatPipelineResult.finish_reason) - reported honestly instead of
    # always claiming success, the Responses API's own vocabulary for this.
    status: Literal["completed", "incomplete"] = "completed"


class OAIResponse(BaseModel):
    id: str
    object: Literal["response"] = "response"
    created_at: int
    model: str
    # "incomplete" when the token budget cut the answer off (see
    # ChatPipelineResult.finish_reason) - reported honestly instead of
    # always claiming success, the Responses API's own vocabulary for this.
    status: Literal["completed", "incomplete"] = "completed"
    # Machine-readable reason for an "incomplete" status, the Responses API's
    # own field for it; null on a completed response.
    incomplete_details: Optional[dict] = None
    output: list[OAIResponseOutputMessage]
    output_text: str
    usage: OAIResponseUsage
    # DejaQ extension, absent unless the semantic tie-breaker fired on a cache
    # hit. `output`/`output_text` still carry the served answer on their own, so
    # a client that ignores unknown keys behaves exactly as it did before.
    # Never set on an attachment request: two entries for one image or file are
    # either two different documents' answers or the same one twice.
    dejaq_drafts: Optional[list[DejaQDraft]] = None


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


class ResponseIncompleteEvent(BaseModel):
    """Terminal event for a stream the token budget cut off.

    The Responses API's own vocabulary: a truncated stream ends on
    `response.incomplete`, not on `response.completed` carrying a contradicting
    status, so a client that branches on the event type sees the truncation.
    """
    type: Literal["response.incomplete"] = "response.incomplete"
    response: dict


class ResponseFailedEvent(BaseModel):
    """Terminal event for a stream that failed outright (e.g. a mid-stream
    local-vision capability rejection - see ChatPipelineResult.failed).

    Same idea as ResponseIncompleteEvent, one step further: the answer never
    started, so there is no output to carry a status on. A client that
    branches on event type gets an unambiguous failure instead of a
    `response.completed` body whose text merely happens to be an apology.
    """
    type: Literal["response.failed"] = "response.failed"
    response: dict
