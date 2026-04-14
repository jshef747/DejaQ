# server/app/routers/openai_compat.py
import hashlib
import logging
import time
import traceback
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import StreamingResponse

from app.schemas.openai_compat import (
    OAIChatChunk,
    OAIChatRequest,
    OAIChatResponse,
    OAIChoice,
    OAIMessageResponse,
    OAIStreamChoice,
    OAIStreamDelta,
    OAIUsage,
)
from app.services.normalizer import NormalizerService
from app.services.llm_router import LLMRouterService, _LOCAL_MODEL_NAME
from app.services.external_llm import ExternalLLMService
from app.services.context_adjuster import ContextAdjusterService
from app.services.memory_chromaDB import MemoryService
from app.services.context_enricher import ContextEnricherService
from app.services import cache_filter
from app.services.classifier import ClassifierService
from app.tasks.cache_tasks import generalize_and_store_task
from app.config import USE_CELERY, EXTERNAL_MODEL_NAME
from app.utils.exceptions import ExternalLLMError
from app.schemas.chat import ExternalLLMRequest

logger = logging.getLogger("dejaq.router.openai_compat")

router = APIRouter()

# --- Service singletons (shared with main process; each service is safe to instantiate once per router module) ---
logger.info("Initializing OpenAI-compat services...")
_normalizer = NormalizerService()
_llm_router = LLMRouterService()
_adjuster = ContextAdjusterService()
_memory = MemoryService()
_enricher = ContextEnricherService()
_classifier = ClassifierService()
_external_llm = ExternalLLMService()
logger.info("OpenAI-compat services ready.")


def _doc_id(clean_query: str) -> str:
    return hashlib.sha256(clean_query.encode()).hexdigest()[:16]


def _now_ts() -> int:
    return int(time.time())


def _new_completion_id() -> str:
    return "chatcmpl-" + uuid.uuid4().hex[:24]


def _is_suppressed(clean_query: str) -> bool:
    import redis as redis_lib
    from app.config import REDIS_URL

    doc_id = _doc_id(clean_query)
    try:
        r = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        return r.exists(f"skip:{doc_id}") == 1
    except redis_lib.exceptions.RedisError:
        return False


def _bg_generalize_and_store(
    clean_query: str, answer: str, original_query: str, tenant_id: str
) -> None:
    if _is_suppressed(clean_query):
        logger.info("Storage suppressed for query '%s'", clean_query[:60])
        return
    try:
        generalized = _adjuster.generalize(answer)
        _memory.store_interaction(clean_query, generalized, original_query, tenant_id)
    except Exception:
        logger.error("Failed to generalize/store: %s", traceback.format_exc())


def _extract_pipeline_inputs(
    request: OAIChatRequest,
) -> tuple[str, list[dict], str | None]:
    """Return (user_query, history_messages, system_prompt_override)."""
    messages = request.messages
    # Last user message is the current query
    user_query: str = ""
    for msg in reversed(messages):
        if msg.role == "user":
            user_query = msg.content
            break

    # Collect system prompt content
    system_parts = [m.content for m in messages if m.role == "system"]
    system_prompt: str | None = "\n".join(system_parts) if system_parts else None

    # History = all messages before the last user message (excluding system messages)
    last_user_idx = -1
    for i in reversed(range(len(messages))):
        if messages[i].role == "user":
            last_user_idx = i
            break

    history: list[dict] = [
        {"role": m.role, "content": m.content}
        for m in messages[:last_user_idx]
        if m.role in ("user", "assistant")
    ]

    return user_query, history, system_prompt


async def _stream_generator(
    chunks: list[str],
    completion_id: str,
    model: str,
    model_used: str,
) -> AsyncGenerator[str, None]:
    """Yield SSE chunks for a list of text pieces, then [DONE]."""
    # First chunk carries role
    first = OAIChatChunk(
        id=completion_id,
        created=_now_ts(),
        model=model,
        choices=[OAIStreamChoice(delta=OAIStreamDelta(role="assistant", content=""))],
    )
    yield f"data: {first.model_dump_json()}\n\n"

    for piece in chunks:
        chunk = OAIChatChunk(
            id=completion_id,
            created=_now_ts(),
            model=model,
            choices=[OAIStreamChoice(delta=OAIStreamDelta(content=piece))],
        )
        yield f"data: {chunk.model_dump_json()}\n\n"

    # Final chunk with finish_reason
    final = OAIChatChunk(
        id=completion_id,
        created=_now_ts(),
        model=model,
        choices=[OAIStreamChoice(delta=OAIStreamDelta(), finish_reason="stop")],
    )
    yield f"data: {final.model_dump_json()}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/chat/completions")
async def chat_completions(
    oai_request: OAIChatRequest,
    raw_request: Request,
    background_tasks: BackgroundTasks,
):
    tenant_id: str = getattr(raw_request.state, "tenant_id", "anonymous")
    logger.info(
        "POST /v1/chat/completions model=%s stream=%s tenant=%s",
        oai_request.model,
        oai_request.stream,
        tenant_id,
    )

    user_query, history, system_prompt = _extract_pipeline_inputs(oai_request)

    if not user_query:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="No user message found in messages array")

    completion_id = _new_completion_id()
    max_tokens = oai_request.max_tokens or 1024

    # 1. Enrich
    try:
        enriched = _enricher.enrich(user_query, history)
    except Exception:
        logger.error("Enricher failed: %s", traceback.format_exc())
        enriched = user_query

    # 2. Normalize
    try:
        clean_query = _normalizer.normalize(enriched)
    except Exception:
        logger.error("Normalizer failed: %s", traceback.format_exc())
        clean_query = enriched

    # 3. Cache lookup
    cache_result = None
    try:
        cache_result = _memory.check_cache(clean_query)
    except Exception:
        logger.error("Cache check failed: %s", traceback.format_exc())

    if cache_result is not None:
        cached_answer, _entry_id, _cache_distance = cache_result
        try:
            answer = _adjuster.adjust(user_query, cached_answer)
        except Exception:
            answer = cached_answer
        model_used = "cache"

        if oai_request.stream:
            words = answer.split(" ")
            chunks = [w + " " for w in words[:-1]] + [words[-1]] if words else [answer]
            headers = {
                "x-dejaq-model-used": model_used,
                "x-dejaq-conversation-id": completion_id,
            }
            return StreamingResponse(
                _stream_generator(chunks, completion_id, oai_request.model, model_used),
                media_type="text/event-stream",
                headers=headers,
            )

        # Non-streaming cache hit
        prompt_tokens = int(len(clean_query.split()) * 1.3)
        response = OAIChatResponse(
            id=completion_id,
            created=_now_ts(),
            model=oai_request.model,
            choices=[OAIChoice(message=OAIMessageResponse(content=answer))],
            usage=OAIUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=0,
                total_tokens=prompt_tokens,
            ),
        )
        from fastapi.responses import JSONResponse

        return JSONResponse(
            content=response.model_dump(),
            headers={
                "x-dejaq-model-used": model_used,
                "x-dejaq-conversation-id": completion_id,
            },
        )

    # 4. Cache miss — classify then route
    try:
        classification = _classifier.predict_complexity(user_query)
    except Exception:
        logger.error("Classifier failed: %s", traceback.format_exc())
        classification = {"complexity": "easy", "score": 0.0, "task_type": "Unknown"}

    complexity = classification["complexity"]
    answer: str = ""
    model_used: str = _LOCAL_MODEL_NAME

    try:
        if complexity == "hard":
            ext_request = ExternalLLMRequest(
                query=user_query,
                history=history,
                model=EXTERNAL_MODEL_NAME,
            )
            ext_response = await _external_llm.generate_response(ext_request)
            answer = ext_response.text
            model_used = ext_response.model_used
        else:
            llm_system_prompt = (
                system_prompt
                or "You are a helpful assistant. Answer the user's query concisely and accurately."
            )
            answer, _ = _llm_router.generate_local_response(
                user_query,
                history=history,
                max_tokens=max_tokens,
                system_prompt=llm_system_prompt,
            )
            model_used = _LOCAL_MODEL_NAME
    except ExternalLLMError as exc:
        logger.error("ExternalLLMService failed: %s", exc)
        answer = "I'm sorry, I couldn't process your request right now. Please try again later."
        model_used = "error"
    except Exception:
        logger.error("LLM generation failed: %s", traceback.format_exc())
        answer = "I'm sorry, I couldn't process your request right now. Please try again later."
        model_used = "error"

    # 5. Cache filter + background store
    will_cache = False
    try:
        will_cache, _ = cache_filter.should_cache(enriched, clean_query)
    except Exception:
        pass

    if will_cache:
        if USE_CELERY:
            generalize_and_store_task.delay(clean_query, answer, user_query, tenant_id)
        else:
            background_tasks.add_task(
                _bg_generalize_and_store, clean_query, answer, user_query, tenant_id
            )

    # 6. Return response
    prompt_tokens = int(len(clean_query.split()) * 1.3)
    completion_tokens = int(len(answer.split()) * 1.3)

    if oai_request.stream:
        words = answer.split(" ")
        chunks = [w + " " for w in words[:-1]] + [words[-1]] if words else [answer]
        headers = {
            "x-dejaq-model-used": model_used,
            "x-dejaq-conversation-id": completion_id,
        }
        return StreamingResponse(
            _stream_generator(chunks, completion_id, oai_request.model, model_used),
            media_type="text/event-stream",
            headers=headers,
        )

    response = OAIChatResponse(
        id=completion_id,
        created=_now_ts(),
        model=oai_request.model,
        choices=[OAIChoice(message=OAIMessageResponse(content=answer))],
        usage=OAIUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )
    from fastapi.responses import JSONResponse

    return JSONResponse(
        content=response.model_dump(),
        headers={
            "x-dejaq-model-used": model_used,
            "x-dejaq-conversation-id": completion_id,
        },
    )
