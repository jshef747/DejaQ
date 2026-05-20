import logging
import time
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.schemas.openai_compat import OAIMessage
from app.schemas.openai_responses import (
    OAIResponse,
    OAIResponseContentPart,
    OAIResponseOutputMessage,
    OAIResponseUsage,
    OAIResponsesContentPart,
    OAIResponsesInputItem,
    OAIResponsesRequest,
    ResponseCompletedEvent,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseCreatedEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
)
from app.routers.openai_compat import ChatPipelineResult, PipelineError, run_chat_pipeline

logger = logging.getLogger("dejaq.router.openai_responses")

router = APIRouter()


def _now_ts() -> int:
    return int(time.time())


def _new_response_id() -> str:
    return "resp-" + uuid.uuid4().hex[:24]


def _new_item_id() -> str:
    return "msg-" + uuid.uuid4().hex[:16]


def _responses_request_to_messages(req: OAIResponsesRequest) -> list[OAIMessage]:
    """Convert Responses API input + instructions into a flat OAIMessage list."""
    msgs: list[OAIMessage] = []

    if req.instructions:
        msgs.append(OAIMessage(role="system", content=req.instructions))

    if isinstance(req.input, str):
        msgs.append(OAIMessage(role="user", content=req.input))
    else:
        for item in req.input:
            if isinstance(item.content, str):
                msgs.append(OAIMessage(role=item.role, content=item.content))
            else:
                text_parts = [
                    p.text or ""
                    for p in item.content
                    if p.type in ("input_text", "output_text") and p.text
                ]
                content = " ".join(text_parts)
                msgs.append(OAIMessage(role=item.role, content=content))

    return msgs


def _build_response_body(
    result: ChatPipelineResult,
    model: str,
    item_id: str,
    response_id: str,
) -> dict:
    return OAIResponse(
        id=response_id,
        created_at=_now_ts(),
        model=model,
        output=[
            OAIResponseOutputMessage(
                id=item_id,
                content=[OAIResponseContentPart(text=result.answer)],
            )
        ],
        output_text=result.answer,
        usage=OAIResponseUsage(
            input_tokens=result.prompt_tokens,
            output_tokens=result.completion_tokens,
            total_tokens=result.prompt_tokens + result.completion_tokens,
        ),
    ).model_dump()


async def _stream_responses_generator(
    result: ChatPipelineResult,
    model: str,
    item_id: str,
    response_id: str,
) -> AsyncGenerator[str, None]:
    partial_response = {
        "id": response_id,
        "object": "response",
        "created_at": _now_ts(),
        "model": model,
        "status": "in_progress",
        "output": [],
    }

    yield f"event: response.created\ndata: {ResponseCreatedEvent(response=partial_response).model_dump_json()}\n\n"

    item_stub = {"id": item_id, "type": "message", "role": "assistant", "content": [], "status": "in_progress"}
    yield f"event: response.output_item.added\ndata: {ResponseOutputItemAddedEvent(item=item_stub).model_dump_json()}\n\n"

    part_stub = {"type": "output_text", "text": ""}
    yield f"event: response.content_part.added\ndata: {ResponseContentPartAddedEvent(item_id=item_id, part=part_stub).model_dump_json()}\n\n"

    full_text = ""
    for piece in result.stream_chunks:
        full_text += piece
        yield (
            f"event: response.output_text.delta\n"
            f"data: {ResponseOutputTextDeltaEvent(item_id=item_id, delta=piece).model_dump_json()}\n\n"
        )

    yield f"event: response.output_text.done\ndata: {ResponseOutputTextDoneEvent(item_id=item_id, text=full_text).model_dump_json()}\n\n"

    part_done = {"type": "output_text", "text": full_text}
    yield f"event: response.content_part.done\ndata: {ResponseContentPartDoneEvent(item_id=item_id, part=part_done).model_dump_json()}\n\n"

    item_done = {
        "id": item_id, "type": "message", "role": "assistant",
        "content": [{"type": "output_text", "text": full_text}],
        "status": "completed",
    }
    yield f"event: response.output_item.done\ndata: {ResponseOutputItemDoneEvent(item=item_done).model_dump_json()}\n\n"

    completed_response = _build_response_body(result, model, item_id, response_id)
    completed_response["status"] = "completed"
    yield f"event: response.completed\ndata: {ResponseCompletedEvent(response=completed_response).model_dump_json()}\n\n"


@router.post("/responses")
async def responses(
    oai_request: OAIResponsesRequest,
    raw_request: Request,
    background_tasks: BackgroundTasks,
):
    messages = _responses_request_to_messages(oai_request)

    try:
        result = await run_chat_pipeline(
            messages=messages,
            model=oai_request.model,
            temperature=oai_request.temperature,
            max_tokens=oai_request.max_output_tokens,
            raw_request=raw_request,
            background_tasks=background_tasks,
        )
    except PipelineError as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    response_id = _new_response_id()
    item_id = _new_item_id()

    if oai_request.stream:
        return StreamingResponse(
            _stream_responses_generator(result, oai_request.model, item_id, response_id),
            media_type="text/event-stream",
            headers=result.headers,
        )

    body = _build_response_body(result, oai_request.model, item_id, response_id)
    return JSONResponse(content=body, headers=result.headers)
