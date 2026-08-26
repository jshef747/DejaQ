import base64
import binascii
import logging
import time
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import MAX_ATTACHMENT_BYTES, RAG_ENABLED
from app.db import rag_document_repo
from app.db.session import get_session
from app.dependencies.auth import ResolvedWorkspace, require_org_key

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
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
)
from app.routers.openai_compat import (
    ChatPipelineResult,
    PipelineError,
    answer_pieces,
    run_chat_pipeline,
)
from app.services.file_text import kind_for as file_kind_for

logger = logging.getLogger("dejaq.router.openai_responses")

router = APIRouter()


def _now_ts() -> int:
    return int(time.time())


def _new_response_id() -> str:
    return "resp-" + uuid.uuid4().hex[:24]


def _new_item_id() -> str:
    return "msg-" + uuid.uuid4().hex[:16]


def _parse_data_url(url: str, what: str = "image", default_mime: str = "image/jpeg") -> tuple[bytes, str]:
    """Decode a `data:<mime>;base64,<payload>` URL into (bytes, mime).

    v1 supports data URLs only (the common upload path). Remote http(s) URLs are
    rejected — fetching them server-side is an SSRF risk not worth it here.
    """
    if not url.startswith("data:"):
        raise PipelineError(400, f"Only data: {what} URLs are supported (base64-encode the {what}).")
    try:
        header, payload = url[len("data:"):].split(",", 1)
        mime = header.split(";", 1)[0] or default_mime
    except ValueError as exc:
        raise PipelineError(400, f"Malformed data {what} URL: {exc}") from exc
    # Reject on the base64 string's own length before decoding — decoding first
    # buffers the payload string plus its decoded bytes (~2x) in memory, so an
    # oversized data URL must be rejected before that allocation happens, not after.
    if (len(payload) * 3) // 4 > MAX_ATTACHMENT_BYTES:
        raise PipelineError(
            400,
            f"Attached {what} is too large; the limit is "
            f"{MAX_ATTACHMENT_BYTES / 1048576:.0f} MB.",
        )
    try:
        data = base64.b64decode(payload)
    except binascii.Error as exc:
        raise PipelineError(400, f"Malformed data {what} URL: {exc}") from exc
    # A client-side size check is not a limit; anything speaking the API directly
    # bypasses it. This is the one that holds.
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise PipelineError(
            400,
            f"Attached {what} is too large ({len(data) / 1048576:.1f} MB); "
            f"the limit is {MAX_ATTACHMENT_BYTES / 1048576:.0f} MB.",
        )
    return data, mime


def _unsupported_file_detail(mime: str, filename: str | None) -> str:
    """Message for an attachment we have no extractor for.

    Same shape as the other attachment 400s: name what arrived, then name what is
    accepted. This is a check on the TYPE, never on the bytes - a PDF we recognise
    but cannot read (a scan, a corrupt file, an encrypted one) is still answered
    normally and is only refused a cache entry. See services/file_text.py.
    """
    described = f"'{mime}'" if mime else "(no type given)"
    if filename:
        described += f" ({filename})"
    return (
        f"Unsupported file type {described}; attach a PDF (.pdf), a Word "
        "document (.docx), or a Markdown/text/code file (any UTF-8 encoded "
        "file, e.g. .md, .txt, .py, .json)."
    )


def _responses_request_to_messages(
    req: OAIResponsesRequest,
) -> tuple[list[OAIMessage], tuple[bytes, str] | None, tuple[bytes, str, str] | None]:
    """Convert Responses API input + instructions into a flat OAIMessage list,
    plus the single attached image as (bytes, mime) and the single attached file
    as (bytes, mime, filename), if present.

    v1 accepts at most ONE attachment across the whole request — one image or one
    file, not several and not both. More than one raises HTTP 400. The single-slot
    rule exists because the cache gate compares one attachment against one stored
    fingerprint; several would need a combined identity that nothing downstream
    understands yet.
    """
    msgs: list[OAIMessage] = []
    image: tuple[bytes, str] | None = None
    file: tuple[bytes, str, str] | None = None

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
                for p in item.content:
                    if p.type == "input_image" and p.image_url:
                        if image is not None:
                            raise PipelineError(400, "At most one image per request is supported.")
                        image = _parse_data_url(p.image_url, "image", "image/jpeg")
                    elif p.type == "input_file" and p.file_data:
                        if file is not None:
                            raise PipelineError(400, "At most one file per request is supported.")
                        # No default MIME. Assuming application/pdf here handed
                        # untyped bytes to pypdf while file_text read the same
                        # empty MIME as Markdown; now both call an absent MIME
                        # unknown and the filename decides.
                        data, mime = _parse_data_url(p.file_data, "file", "")
                        # A type we have no extractor for used to be decoded,
                        # logged and then dropped, and the request answered 200
                        # as if nothing had been attached. Reject it like every
                        # other unusable attachment shape instead.
                        if not file_kind_for(data, mime, p.filename):
                            raise PipelineError(400, _unsupported_file_detail(mime, p.filename))
                        file = (data, mime, p.filename or "")
                msgs.append(OAIMessage(role=item.role, content=" ".join(text_parts)))

    if image is not None and file is not None:
        raise PipelineError(400, "Attach either an image or a file, not both.")

    return msgs, image, file


def _build_response_body(
    result: ChatPipelineResult,
    model: str,
    item_id: str,
    response_id: str,
) -> dict:
    status = "incomplete" if result.finish_reason == "length" else "completed"
    return OAIResponse(
        id=response_id,
        created_at=_now_ts(),
        model=model,
        status=status,
        incomplete_details={"reason": "max_output_tokens"} if status == "incomplete" else None,
        output=[
            OAIResponseOutputMessage(
                id=item_id,
                content=[OAIResponseContentPart(text=result.answer)],
                status=status,
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
    async for piece in answer_pieces(result):
        full_text += piece
        yield (
            f"event: response.output_text.delta\n"
            f"data: {ResponseOutputTextDeltaEvent(item_id=item_id, delta=piece).model_dump_json()}\n\n"
        )

    # A failure (result.failed, e.g. a local-vision capability rejection
    # discovered mid-stream) yields no text above - full_text is empty here.
    # Ending on `response.failed` instead of the usual done/completed events
    # is what stops this from rendering as an answered response: without it,
    # a client sees content_part.added -> ... -> completed with empty/apology
    # text and no way to distinguish that from a real (if terse) answer.
    if result.failed:
        failed_response = {
            "id": response_id,
            "object": "response",
            "created_at": _now_ts(),
            "model": model,
            "status": "failed",
            "error": {"message": result.error_detail or "Generation failed."},
            "output": [],
            "output_text": "",
        }
        yield f"event: response.failed\ndata: {ResponseFailedEvent(response=failed_response).model_dump_json()}\n\n"
        return

    # One message, one text. `result.answer` is the canonical answer - stripped
    # on the streaming path exactly as OllamaBackend strips it on the buffered
    # one - and it is what the terminal `response.completed` body carries, so
    # the done events below have to carry the same string rather than the raw
    # concatenation of the deltas. Only settled once the loop above drains.
    full_text = result.answer or full_text

    yield f"event: response.output_text.done\ndata: {ResponseOutputTextDoneEvent(item_id=item_id, text=full_text).model_dump_json()}\n\n"

    part_done = {"type": "output_text", "text": full_text}
    yield f"event: response.content_part.done\ndata: {ResponseContentPartDoneEvent(item_id=item_id, part=part_done).model_dump_json()}\n\n"

    status = "incomplete" if result.finish_reason == "length" else "completed"
    item_done = {
        "id": item_id, "type": "message", "role": "assistant",
        "content": [{"type": "output_text", "text": full_text}],
        "status": status,
    }
    yield f"event: response.output_item.done\ndata: {ResponseOutputItemDoneEvent(item=item_done).model_dump_json()}\n\n"

    final_response = _build_response_body(result, model, item_id, response_id)
    # A truncated stream ends on its own terminal event. Sending
    # `response.completed` with a payload that says "incomplete" tells a client
    # that branches on the event type the opposite of what happened.
    terminal = (
        ResponseIncompleteEvent(response=final_response)
        if status == "incomplete"
        else ResponseCompletedEvent(response=final_response)
    )
    yield f"event: {terminal.type}\ndata: {terminal.model_dump_json()}\n\n"


@router.post("/responses")
async def responses(
    oai_request: OAIResponsesRequest,
    raw_request: Request,
    background_tasks: BackgroundTasks,
    resolved_workspace: ResolvedWorkspace = Depends(require_org_key),
):
    rag_document_title: str | None = None
    rag_group_document_ids: list[int] | None = None
    if oai_request.rag_document_id is not None and oai_request.rag_group_key is not None:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "Send either rag_document_id (one file) or rag_group_key "
                "(a whole imported repository), not both."
            },
        )
    if oai_request.rag_document_id is not None or oai_request.rag_group_key is not None:
        if not RAG_ENABLED:
            return JSONResponse(
                status_code=400,
                content={"detail": "RAG is disabled on this server (DEJAQ_RAG_ENABLED=false)."},
            )
    if oai_request.rag_document_id is not None:
        with get_session() as session:
            rag_doc = rag_document_repo.get(
                session, resolved_workspace.workspace_id, oai_request.rag_document_id
            )
            if rag_doc is None:
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": f"rag_document_id {oai_request.rag_document_id} not found "
                        "in this workspace."
                    },
                )
            rag_document_title = rag_doc.title
    elif oai_request.rag_group_key is not None:
        # Resolved here for the same reason the single-document title is: the
        # pipeline never re-queries the catalog. An empty group is a 400 rather
        # than a silent ungrounded answer — the client is referencing something
        # that no longer exists (deleted, or a stale picker list).
        with get_session() as session:
            group_docs = rag_document_repo.list_for_group(
                session, resolved_workspace.workspace_id, oai_request.rag_group_key
            )
            if not group_docs:
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": f"rag_group_key {oai_request.rag_group_key!r} not found "
                        "in this workspace."
                    },
                )
            rag_group_document_ids = [d.id for d in group_docs]
            rag_document_title = oai_request.rag_group_key.replace("github:", "", 1)

    try:
        messages, image, file = _responses_request_to_messages(oai_request)
        result = await run_chat_pipeline(
            messages=messages,
            model=oai_request.model,
            temperature=oai_request.temperature,
            max_tokens=oai_request.max_output_tokens,
            raw_request=raw_request,
            background_tasks=background_tasks,
            image=image,
            file=file,
            rag_document_id=oai_request.rag_document_id,
            rag_group_key=oai_request.rag_group_key,
            rag_group_document_ids=rag_group_document_ids,
            rag_document_title=rag_document_title,
            stream=bool(oai_request.stream),
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
