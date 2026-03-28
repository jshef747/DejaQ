# server/app/routers/chat.py
import hashlib
import logging
import json
import traceback
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, BackgroundTasks, HTTPException, Query
from app.schemas.chat import ChatRequest, ChatResponse, ExternalLLMRequest
from app.services.normalizer import NormalizerService
from app.services.llm_router import LLMRouterService, _LOCAL_MODEL_NAME
from app.services.external_llm import ExternalLLMService
from app.services.context_adjuster import ContextAdjusterService
from app.services.memory_chromaDB import MemoryService
from app.services.conversation_store import ConversationStore
from app.services.context_enricher import ContextEnricherService
from app.services import cache_filter
from app.services.classifier import ClassifierService
from app.tasks.cache_tasks import generalize_and_store_task
from app.config import USE_CELERY, EXTERNAL_MODEL_NAME
from app.utils.exceptions import ExternalLLMError

# Setup logger
logger = logging.getLogger("dejaq.router.chat")

router = APIRouter()


def _compute_doc_id(clean_query: str) -> str:
    return hashlib.sha256(clean_query.encode()).hexdigest()[:16]

# Initialize Services (Global)
logger.info("Initializing Normalizer Service...")
normalizer = NormalizerService()
logger.info("Normalizer Service Ready.")

logger.info("Initializing LLM Router Service...")
llm_router = LLMRouterService()
logger.info("LLM Router Service Ready.")

logger.info("Initializing Context Adjuster Service...")
context_adjuster = ContextAdjusterService()
logger.info("Context Adjuster Service Ready.")

logger.info("Initializing Memory Service (ChromaDB)...")
memory = MemoryService()
logger.info("Memory Service Ready.")

logger.info("Initializing Conversation Store...")
conversations = ConversationStore()
logger.info("Conversation Store Ready.")

logger.info("Initializing Context Enricher Service...")
enricher = ContextEnricherService()
logger.info("Context Enricher Service Ready.")

logger.info("Initializing Classifier Service...")
classifier = ClassifierService()
logger.info("Classifier Service Ready.")

external_llm = ExternalLLMService()


def _is_suppressed(clean_query: str) -> bool:
    """Check if negative feedback has suppressed storage for this query."""
    import redis as redis_lib
    from app.config import REDIS_URL
    doc_id = hashlib.sha256(clean_query.encode()).hexdigest()[:16]
    try:
        r = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        return r.exists(f"skip:{doc_id}") == 1
    except redis_lib.exceptions.RedisError:
        return False


def _generalize_and_store(
    clean_query: str, answer: str, original_query: str, user_id: str
) -> None:
    """Generalize an LLM answer and store it in the cache. Safe to call from background tasks."""
    if _is_suppressed(clean_query):
        logger.info("Storage suppressed (in-process) for query '%s'", clean_query[:60])
        return
    try:
        generalized = context_adjuster.generalize(answer)
        memory.store_interaction(clean_query, generalized, original_query, user_id)
    except Exception:
        logger.error("Failed to generalize/store: %s", traceback.format_exc())


@router.post("/normalize", response_model=ChatResponse)
async def normalize_endpoint(request: ChatRequest):
    logger.info(f"POST /normalize from user={request.user_id}")
    clean_query = normalizer.normalize(request.message)
    logger.info(f"Normalized query: {clean_query}")
    return ChatResponse(
        sender="system",
        message=clean_query,
        normalized_query=clean_query,
        status="ok",
    )


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, background_tasks: BackgroundTasks):
    logger.info(f"POST /chat from user={request.user_id}")

    # 0. Resolve conversation
    conv_id = conversations.get_or_create(request.conversation_id)
    history = conversations.get_history(conv_id)

    # 1. Enrich — rewrite context-dependent queries into standalone ones
    enriched = enricher.enrich(request.message, history)
    enriched_changed = enriched != request.message

    # 2. Normalize the enriched query (better cache key)
    clean_query = normalizer.normalize(enriched)
    logger.info(f"Normalized query: {clean_query}")

    # 3. Check cache with enriched+normalized key
    cache_result = memory.check_cache(clean_query)

    if cache_result is not None:
        cached_answer, entry_id = cache_result
        # Cache HIT — adjust tone to match original query
        answer = context_adjuster.adjust(request.message, cached_answer)
        conversations.add_message(conv_id, "user", request.message)
        conversations.add_message(conv_id, "assistant", answer)
        return ChatResponse(
            sender="bot",
            message=answer,
            normalized_query=clean_query,
            status="ok",
            cache_hit=True,
            conversation_id=conv_id,
            enriched_query=enriched if enriched_changed else None,
            cache_entry_id=entry_id,
        )

    # 4. Classify complexity
    classification = classifier.predict_complexity(request.message)
    complexity = classification["complexity"]

    # 5. Cache MISS — route to local or external LLM (original query + history preserves tone)
    model_used = None
    latency_ms = None
    if complexity == "hard":
        logger.info("Routing 'hard' query to ExternalLLMService")
        try:
            ext_request = ExternalLLMRequest(
                query=request.message,
                history=history,
                model=EXTERNAL_MODEL_NAME,
            )
            ext_response = await external_llm.generate_response(ext_request)
            answer = ext_response.text
            model_used = ext_response.model_used
            latency_ms = ext_response.latency_ms
        except ExternalLLMError as exc:
            logger.error("ExternalLLMService failed: %s", exc)
            return ChatResponse(
                sender="bot",
                message="I'm sorry, I couldn't process your request right now. The external service is unavailable. Please try again later.",
                normalized_query=clean_query,
                status="error",
                cache_hit=False,
                conversation_id=conv_id,
            )
    else:
        answer, latency_ms = llm_router.generate_local_response(request.message, history=history)
        model_used = _LOCAL_MODEL_NAME

    logger.info("LLM answer length: %d (model=%s)", len(answer), model_used)

    # 6. Store in conversation history
    conversations.add_message(conv_id, "user", request.message)
    conversations.add_message(conv_id, "assistant", answer)

    # 7. Smart cache filter — decide if this response is worth caching
    will_cache, filter_reason = cache_filter.should_cache(enriched, clean_query)

    if will_cache:
        # 8. Generalize + store in background (user doesn't wait for Phi-3.5)
        if USE_CELERY:
            generalize_and_store_task.delay(clean_query, answer, request.message, request.user_id)
        else:
            background_tasks.add_task(
                _generalize_and_store, clean_query, answer, request.message, request.user_id
            )

    return ChatResponse(
        sender="bot",
        message=answer,
        normalized_query=clean_query,
        status="ok",
        cache_hit=False,
        conversation_id=conv_id,
        enriched_query=enriched if enriched_changed else None,
        cached=will_cache,
        complexity=complexity,
        complexity_score=classification["score"],
        task_type=classification["task_type"],
        cache_entry_id=_compute_doc_id(clean_query) if will_cache else None,
        model_used=model_used,
        latency_ms=latency_ms,
    )


@router.post("/generalize", response_model=ChatResponse)
async def generalize_endpoint(request: ChatRequest):
    logger.info(f"POST /generalize from user={request.user_id}")
    generalized = context_adjuster.generalize(request.message)
    logger.info(f"Generalized answer length: {len(generalized)}")
    return ChatResponse(
        sender="system",
        message=generalized,
        normalized_query=request.message,
        status="ok",
    )


# --- Cache Viewer Endpoints ---

@router.get("/cache/entries")
async def get_cache_entries(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    entries = memory.get_all_entries(limit=limit, offset=offset)
    return {
        "total": memory.count,
        "entries": entries,
    }


@router.delete("/cache/entries/{entry_id}")
async def delete_cache_entry(entry_id: str):
    deleted = memory.delete_entry(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Cache entry not found")
    return {"status": "deleted"}


# --- Conversation Endpoints ---

@router.get("/conversations")
async def list_conversations():
    return conversations.list_conversations()


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: str):
    history = conversations.get_history(conversation_id)
    if not history and conversation_id not in conversations._conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return history


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    deleted = conversations.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted"}


# --- WebSocket ---

@router.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    logger.debug("New WebSocket connection request received.")
    await websocket.accept()
    logger.debug("Connection accepted. Entering loop.")

    # Each WebSocket connection starts a conversation (may be resumed via first message)
    conv_id = None

    try:
        while True:
            # 1. Wait for data
            logger.debug("Waiting for client message...")
            data = await websocket.receive_text()
            logger.debug(f"Received raw data: {data}")

            # 2. Validate
            try:
                payload = json.loads(data)
                request_data = ChatRequest(**payload)
                logger.debug("Validation successful.")
            except Exception as e:
                logger.error(f"Validation FAILED: {e}")
                await websocket.close(code=1008, reason="Invalid Schema")
                break

            # 2b. Resolve conversation (first message may carry an existing conversation_id)
            if conv_id is None:
                conv_id = conversations.get_or_create(request_data.conversation_id)
            history = conversations.get_history(conv_id)

            # 3. Enrich — rewrite context-dependent queries into standalone ones
            try:
                enriched = enricher.enrich(request_data.message, history)
                enriched_changed = enriched != request_data.message
            except Exception as e:
                logger.error(f"CRASH IN ENRICHER: {e}")
                traceback.print_exc()
                enriched = request_data.message
                enriched_changed = False

            # 4. Normalize the enriched query
            logger.debug("Starting normalization...")
            try:
                clean_query = normalizer.normalize(enriched)
                logger.debug(f"Normalization result: {clean_query}")
            except Exception as e:
                logger.error(f"CRASH IN NORMALIZER: {e}")
                traceback.print_exc()
                clean_query = request_data.message  # Fallback

            # 5. Check cache with enriched+normalized key
            cache_hit = False
            will_cache = None
            entry_id = None
            try:
                cache_result = memory.check_cache(clean_query)
            except Exception as e:
                logger.error(f"Cache check failed: {e}")
                cache_result = None

            classification = None
            model_used = None
            latency_ms = None
            if cache_result is not None:
                cached_answer, entry_id = cache_result
                # Cache HIT — adjust tone
                cache_hit = True
                try:
                    answer = context_adjuster.adjust(request_data.message, cached_answer)
                except Exception as e:
                    logger.error(f"CRASH IN CONTEXT ADJUSTER (adjust): {e}")
                    traceback.print_exc()
                    answer = cached_answer  # Fallback to neutral answer
            else:
                cached_answer = None
                # Cache MISS — classify complexity then route to local or external LLM
                try:
                    classification = classifier.predict_complexity(request_data.message)
                except Exception as e:
                    logger.error(f"CRASH IN CLASSIFIER: {e}")
                    traceback.print_exc()
                    classification = {"complexity": "easy", "score": 0.0, "task_type": "Unknown"}

                logger.debug("Generating LLM response (complexity=%s)...", classification["complexity"])
                try:
                    if classification["complexity"] == "hard":
                        logger.info("Routing 'hard' query to ExternalLLMService (WebSocket)")
                        ext_request = ExternalLLMRequest(
                            query=request_data.message,
                            history=history,
                            model=EXTERNAL_MODEL_NAME,
                        )
                        ext_response = await external_llm.generate_response(ext_request)
                        answer = ext_response.text
                        model_used = ext_response.model_used
                        latency_ms = ext_response.latency_ms
                    else:
                        answer, latency_ms = llm_router.generate_local_response(request_data.message, history=history)
                        model_used = _LOCAL_MODEL_NAME
                    logger.debug("LLM answer length: %d (model=%s)", len(answer), model_used)
                except ExternalLLMError as e:
                    logger.error("ExternalLLMService failed (WebSocket): %s", e)
                    answer = "I'm sorry, I couldn't process your request right now. The external service is unavailable. Please try again later."
                    model_used = None
                except Exception as e:
                    logger.error(f"CRASH IN LLM: {e}")
                    traceback.print_exc()
                    answer = f"I processed your request. Cleaned Query: '{clean_query}'"

            # 6. Store in conversation history (both cache hits and misses)
            conversations.add_message(conv_id, "user", request_data.message)
            conversations.add_message(conv_id, "assistant", answer)

            # 7. Smart cache filter (decide before sending so we can include the badge)
            if not cache_hit and cached_answer is None:
                will_cache, filter_reason = cache_filter.should_cache(enriched, clean_query)

            # 8. Send Response FIRST (user doesn't wait for generalization)
            response = ChatResponse(
                sender="bot",
                message=answer,
                normalized_query=clean_query,
                status="ok",
                cache_hit=cache_hit,
                conversation_id=conv_id,
                enriched_query=enriched if enriched_changed else None,
                cached=will_cache,
                complexity=classification["complexity"] if classification else None,
                complexity_score=classification["score"] if classification else None,
                task_type=classification["task_type"] if classification else None,
                cache_entry_id=entry_id if cache_hit else (_compute_doc_id(clean_query) if will_cache else None),
                model_used=model_used,
                latency_ms=latency_ms,
            )

            await websocket.send_text(response.model_dump_json())
            logger.debug("Response sent.")

            # 9. AFTER sending: generalize + store in background
            if will_cache:
                if USE_CELERY:
                    generalize_and_store_task.delay(
                        clean_query, answer, request_data.message, request_data.user_id
                    )
                else:
                    _generalize_and_store(
                        clean_query, answer, request_data.message, request_data.user_id
                    )

    except WebSocketDisconnect:
        logger.debug("Client disconnected gracefully.")
    except Exception as e:
        logger.error(f"CRITICAL UNHANDLED ERROR: {e}")
        traceback.print_exc()
