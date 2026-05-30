# server/app/routers/openai_compat.py
import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.schemas.openai_compat import (
    OAIChatChunk,
    OAIChatRequest,
    OAIChatResponse,
    OAIChoice,
    OAIMessage,
    OAIMessageResponse,
    OAIStreamChoice,
    OAIStreamDelta,
    OAIUsage,
)
from app.services.llm_router import _LOCAL_MODEL_NAME
from app.services.external_llm import ExternalLLMService
from app.services.credential_service import CredentialService, SUPPORTED_PROVIDERS
from app.services.llm_providers import LIVE_PROVIDERS
from app.services.memory_chromaDB import CacheLookupResult, get_memory_service
from app.services.provider_inference import provider_for_model
from app.services import cache_filter, llm_config_service
from app.services.classifier import ClassifierService
from app.services.service_factory import (
    get_context_adjuster_service,
    get_context_enricher_service,
    get_llm_router_service,
    get_normalizer_service,
    get_validator_service,
)
from app.tasks.cache_tasks import generalize_and_store_task
from app.config import USE_CELERY, EXTERNAL_MODEL_NAME, ROUTING_THRESHOLD, VALIDATOR_ENABLED
from app.db.session import get_session
from app.utils.exceptions import ExternalLLMError
from app.utils.logger import clear_request_id, content_snippet, set_request_id
from app.utils.pipeline_trace import PipelineTrace
from app.schemas.chat import ExternalLLMRequest
from app.services.chat_messages import extract_pipeline_inputs
from app.services.request_logger import request_logger
from app.services.response_registry import ResponseInteraction, ServedTier, response_registry

logger = logging.getLogger("dejaq.router.openai_compat")

router = APIRouter()

MODEL_PROFILE_DEFAULT = "default"
MODEL_PROFILE_WEAK_CPU = "weak_cpu"
ROUTING_MODE_AUTO = "auto"
ROUTING_MODE_EASY_LOCAL = "easy_local"
ROUTING_MODE_HARD_EXTERNAL = "hard_external"
WEAK_CPU_MODEL_NAME = "qwen_0_5b"


@dataclass(frozen=True)
class ModelServices:
    normalizer: object
    llm_router: object
    adjuster: object
    enricher: object
    validator: object


@dataclass(frozen=True)
class EffectiveLlmConfig:
    external_model: str
    routing_threshold: float


# --- Service singletons (shared with main process; each service is safe to instantiate once per router module) ---
logger.info("Initializing OpenAI-compat services...")
_normalizer = get_normalizer_service()
_llm_router = get_llm_router_service()
_adjuster = get_context_adjuster_service()
_enricher = get_context_enricher_service()
_validator = get_validator_service()
_classifier = ClassifierService()
_external_llm = ExternalLLMService()
# MemoryService is namespace-aware; use get_memory_service(namespace) per-request
logger.info("OpenAI-compat services ready.")


class PipelineError(Exception):
    """Raised by run_chat_pipeline for HTTP-level failures; callers convert to JSONResponse."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@dataclass
class ChatPipelineResult:
    answer: str
    response_id: str | None
    completion_id: str
    model_used: str
    stream_chunks: list[str]
    headers: dict[str, str]
    prompt_tokens: int
    completion_tokens: int


def _request_model_profile(raw_request: Request) -> str:
    value = raw_request.headers.get("X-DejaQ-Model-Profile", MODEL_PROFILE_DEFAULT).strip().lower()
    if value == MODEL_PROFILE_WEAK_CPU:
        return MODEL_PROFILE_WEAK_CPU
    return MODEL_PROFILE_DEFAULT


def _request_routing_mode(raw_request: Request) -> str:
    value = raw_request.headers.get("X-DejaQ-Routing-Mode", ROUTING_MODE_AUTO).strip().lower()
    if value in {ROUTING_MODE_AUTO, ROUTING_MODE_EASY_LOCAL, ROUTING_MODE_HARD_EXTERNAL}:
        return value
    return ROUTING_MODE_AUTO


def _read_effective_llm_config(org_slug: str, org_id: int | None) -> EffectiveLlmConfig:
    if org_id is None:
        return EffectiveLlmConfig(
            external_model=EXTERNAL_MODEL_NAME,
            routing_threshold=ROUTING_THRESHOLD,
        )
    try:
        config = llm_config_service.read_for_org(org_slug)
    except llm_config_service.OrgNotFound:
        logger.warning("LLM config requested for missing org slug=%s; using defaults", org_slug)
        return EffectiveLlmConfig(
            external_model=EXTERNAL_MODEL_NAME,
            routing_threshold=ROUTING_THRESHOLD,
        )
    return EffectiveLlmConfig(
        external_model=config.external_model,
        routing_threshold=config.routing_threshold,
    )


def _services_for_model_profile(model_profile: str) -> ModelServices:
    # Temporary developer-only weak CPU profile. Keep the default singleton path
    # unchanged so production behavior and existing tests remain stable.
    if model_profile == MODEL_PROFILE_WEAK_CPU:
        return ModelServices(
            normalizer=get_normalizer_service(model_name=WEAK_CPU_MODEL_NAME),
            llm_router=get_llm_router_service(model_name=WEAK_CPU_MODEL_NAME),
            adjuster=get_context_adjuster_service(
                adjust_model_name=WEAK_CPU_MODEL_NAME,
                generalize_model_name=WEAK_CPU_MODEL_NAME,
            ),
            enricher=get_context_enricher_service(model_name=WEAK_CPU_MODEL_NAME),
            validator=_validator,
        )
    return ModelServices(
        normalizer=_normalizer,
        llm_router=_llm_router,
        adjuster=_adjuster,
        enricher=_enricher,
        validator=_validator,
    )


def _local_model_used(llm_router: object, model_profile: str) -> str:
    if model_profile == MODEL_PROFILE_WEAK_CPU:
        return str(getattr(llm_router, "model_name", WEAK_CPU_MODEL_NAME))
    return _LOCAL_MODEL_NAME


def _doc_id(clean_query: str) -> str:
    return hashlib.sha256(clean_query.encode()).hexdigest()[:16]


def _now_ts() -> int:
    return int(time.time())


def _new_completion_id() -> str:
    return "chatcmpl-" + uuid.uuid4().hex[:24]


def _short_request_id(completion_id: str) -> str:
    return completion_id[:17]


def _diagnostic_prompt(text: str | None, limit: int = 200) -> str | None:
    if not text:
        return None
    prompt = " ".join(text.split())
    if not prompt:
        return None
    if len(prompt) <= limit:
        return prompt
    return prompt[:limit]


def _nearest_headers(cache_lookup: CacheLookupResult) -> dict[str, str]:
    prompt = _diagnostic_prompt(cache_lookup.nearest_prompt)
    if cache_lookup.nearest_distance is None or prompt is None:
        return {}
    return {
        "x-dejaq-nearest-cache-distance": f"{cache_lookup.nearest_distance:.4f}",
        "x-dejaq-nearest-cache-prompt": prompt,
    }


def _nearest_log_suffix(cache_lookup: CacheLookupResult) -> str:
    prompt = _diagnostic_prompt(cache_lookup.nearest_prompt)
    if cache_lookup.nearest_distance is None or prompt is None:
        return ""
    return f" nearest_distance={cache_lookup.nearest_distance:.4f} nearest_prompt={prompt}"


def _enriched_log_suffix(enriched: str, enrich_succeeded: bool) -> str:
    if not enrich_succeeded:
        return ""
    prompt = _diagnostic_prompt(enriched)
    if prompt is None:
        return ""
    return f" enriched_prompt={prompt}"


def _legacy_cache_lookup(cache_result: tuple[str, ...] | None) -> CacheLookupResult:
    if cache_result is None:
        return CacheLookupResult(hit=False)
    if len(cache_result) == 3:
        answer, entry_id, distance = cache_result
        matched_query = ""
    else:
        answer, entry_id, distance, matched_query = cache_result[:4]
    return CacheLookupResult(
        hit=True,
        generalized_answer=answer,
        entry_id=entry_id,
        distance=float(distance),
        matched_query=matched_query,
        nearest_distance=float(distance),
        nearest_prompt=matched_query or None,
    )


def _cache_lookup(memory: object, clean_query: str) -> CacheLookupResult:
    lookup = getattr(memory, "lookup_cache", None)
    if callable(lookup):
        return lookup(clean_query)
    check_cache = getattr(memory, "check_cache")
    return _legacy_cache_lookup(check_cache(clean_query))


def _bg_generalize_and_store(
    clean_query: str,
    answer: str,
    original_query: str,
    tenant_id: str,
    cache_namespace: str = "dejaq_default",
    model_profile: str = MODEL_PROFILE_DEFAULT,
) -> None:
    start = time.perf_counter()
    doc_id = _doc_id(clean_query)
    try:
        generalized = asyncio.run(_services_for_model_profile(model_profile).adjuster.generalize(answer))
        memory = get_memory_service(cache_namespace)
        doc_id = memory.store_interaction(clean_query, generalized, original_query, tenant_id)
        latency_ms = int((time.perf_counter() - start) * 1000)
        query = content_snippet(clean_query)
        if query:
            logger.info(
                "background_store status=stored namespace=%s doc_id=%s latency=%dms query=%s",
                cache_namespace,
                doc_id,
                latency_ms,
                query,
            )
        else:
            logger.info(
                "background_store status=stored namespace=%s doc_id=%s latency=%dms",
                cache_namespace,
                doc_id,
                latency_ms,
            )
    except Exception:
        logger.exception("background_store status=failed namespace=%s doc_id=%s", cache_namespace, doc_id)


async def _increment_hit_count_bg(namespace: str, doc_id: str) -> None:
    try:
        get_memory_service(namespace).increment_hit_count(doc_id)
    except Exception:
        logger.warning("Failed to increment hit_count for %s:%s", namespace, doc_id)


async def _register_answer_interaction(
    *,
    org_id: int | None,
    org_slug: str,
    department: str,
    cache_namespace: str,
    served_tier: ServedTier,
    response_id: str | None,
    request_messages: list[object],
) -> ResponseInteraction:
    try:
        return await response_registry.register(
            org_id=org_id,
            org_slug=org_slug,
            department=department,
            cache_namespace=cache_namespace,
            served_tier=served_tier,
            response_id=response_id,
            messages=request_messages,
        )
    except RuntimeError:
        # Tests often call the app without lifespan. Production initializes this
        # in main.lifespan before requests are served.
        await response_registry.init()
        return await response_registry.register(
            org_id=org_id,
            org_slug=org_slug,
            department=department,
            cache_namespace=cache_namespace,
            served_tier=served_tier,
            response_id=response_id,
            messages=request_messages,
        )


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


async def run_chat_pipeline(
    *,
    messages: list[OAIMessage],
    model: str,
    temperature: float | None,
    max_tokens: int | None,
    raw_request: Request,
    background_tasks: BackgroundTasks,
) -> ChatPipelineResult:
    """Core DejaQ pipeline: enrich → normalize → cache → validate → adjust/generate → store.

    Raises PipelineError for HTTP-level failures (402, 422, 500).
    """
    _t0 = time.monotonic()
    trace = PipelineTrace()
    cache_namespace: str = getattr(raw_request.state, "cache_namespace", "dejaq_default")
    org_slug: str = getattr(raw_request.state, "org_slug", "anonymous")
    org_id: int | None = getattr(raw_request.state, "org_id", None)
    dept = raw_request.headers.get("X-DejaQ-Department") or "default"

    # Adapt message list into a minimal OAIChatRequest-like object for extract_pipeline_inputs
    _pseudo_request = type("_PseudoRequest", (), {"messages": messages})()
    user_query, history, system_prompt = extract_pipeline_inputs(list(messages))

    if not user_query:
        raise PipelineError(422, "No user message found in messages array")

    completion_id = _new_completion_id()
    request_token = set_request_id(_short_request_id(completion_id))
    _max_tokens = max_tokens or 1024
    model_profile = _request_model_profile(raw_request)
    routing_mode = _request_routing_mode(raw_request)
    llm_config = await run_in_threadpool(_read_effective_llm_config, org_slug, org_id)
    services = _services_for_model_profile(model_profile)

    try:
        query = content_snippet(user_query)
        if query:
            logger.info(
                "start org=%s dept=%s namespace=%s model=%s query=%s",
                org_slug, dept, cache_namespace, model, query,
            )
        else:
            logger.info(
                "start org=%s dept=%s namespace=%s model=%s",
                org_slug, dept, cache_namespace, model,
            )

        # 1. Enrich
        enrich_succeeded = False
        try:
            with trace.step("enrich"):
                enriched = await services.enricher.enrich(user_query, history)
                enrich_succeeded = True
        except Exception:
            logger.exception("Enricher failed")
            enriched = user_query

        # 2. Normalize
        try:
            with trace.step("normalize"):
                clean_query = await services.normalizer.normalize(enriched)
        except Exception:
            logger.exception("Normalizer failed")
            clean_query = enriched

        # 3. Cache lookup
        cache_lookup = CacheLookupResult(hit=False)
        try:
            with trace.step("cache"):
                cache_lookup = _cache_lookup(get_memory_service(cache_namespace), clean_query)
        except Exception:
            logger.exception("Cache check failed")

        _validator_verdict: str | None = None
        if cache_lookup.hit:
            cached_answer = cache_lookup.generalized_answer or ""
            _entry_id = cache_lookup.entry_id or ""
            _cache_distance = float(cache_lookup.distance or 0.0)
            _cache_matched_query = _diagnostic_prompt(cache_lookup.matched_query) or ""

            _validator_accepted = True
            if VALIDATOR_ENABLED:
                try:
                    with trace.step("validate"):
                        _validator_accepted, _validator_verdict = await services.validator.validate(
                            user_query,
                            cache_lookup.matched_query or "",
                            cached_answer,
                        )
                except Exception:
                    logger.exception("Validator failed; treating as cache miss (fail-safe)")
                    _validator_accepted = False

            if not _validator_accepted:
                cache_lookup = CacheLookupResult(
                    hit=False,
                    nearest_distance=_cache_distance,
                    nearest_prompt=cache_lookup.matched_query,
                )
                logger.info(
                    "validator rejected cache hit distance=%.4f matched_query=%r steps=%s",
                    _cache_distance, _cache_matched_query, trace.summary(),
                )
            else:
                try:
                    with trace.step("adjust"):
                        answer = await services.adjuster.adjust(user_query, cached_answer)
                except Exception:
                    logger.exception("Context adjuster failed")
                    answer = cached_answer
                model_used = "cache"

                response_id = f"{cache_namespace}:{_entry_id}"
                interaction = await _register_answer_interaction(
                    org_id=org_id,
                    org_slug=org_slug,
                    department=dept,
                    cache_namespace=cache_namespace,
                    served_tier="cache",
                    response_id=response_id,
                    request_messages=list(messages),
                )
                _latency = int((time.monotonic() - _t0) * 1000)
                asyncio.create_task(request_logger.log(org_slug, dept, _latency, True, None, None, response_id))
                asyncio.create_task(_increment_hit_count_bg(cache_namespace, _entry_id))
                logger.info(
                    "done cache=hit route=cache model=%s response_id=%s latency=%dms steps=%s%s%s",
                    model_used, response_id, _latency, trace.summary(),
                    _enriched_log_suffix(enriched, enrich_succeeded),
                    _nearest_log_suffix(cache_lookup),
                )

                prompt_tokens = int(len(clean_query.split()) * 1.3)
                words = answer.split(" ")
                stream_chunks = [w + " " for w in words[:-1]] + [words[-1]] if words else [answer]
                hit_headers: dict[str, str] = {
                    "x-dejaq-model-used": model_used,
                    "x-dejaq-conversation-id": completion_id,
                    "x-dejaq-interaction-id": interaction.interaction_id,
                    "x-dejaq-tier": "cache",
                    "x-dejaq-response-id": response_id,
                    "x-dejaq-cache-distance": f"{_cache_distance:.4f}",
                    "x-dejaq-cache-matched-query": _cache_matched_query,
                    "x-dejaq-validator-verdict": "valid",
                }
                hit_headers.update(_nearest_headers(cache_lookup))
                return ChatPipelineResult(
                    answer=answer,
                    response_id=response_id,
                    completion_id=completion_id,
                    model_used=model_used,
                    stream_chunks=stream_chunks,
                    headers=hit_headers,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=0,
                )

        # 4. Cache miss — classify then route
        if routing_mode == ROUTING_MODE_EASY_LOCAL:
            classification = {"complexity": "easy", "score": 0.0, "task_type": "forced_local"}
        elif routing_mode == ROUTING_MODE_HARD_EXTERNAL:
            classification = {"complexity": "hard", "score": 1.0, "task_type": "forced_external"}
        else:
            try:
                with trace.step("classify"):
                    classification = _classifier.predict_complexity(user_query)
            except Exception:
                logger.exception("Classifier failed")
                classification = {"complexity": "easy", "score": 0.0, "task_type": "Unknown"}
            else:
                score = float(classification.get("score", 0.0))
                classification = {
                    **classification,
                    "complexity": "hard" if score >= llm_config.routing_threshold else "easy",
                }

        complexity = classification["complexity"]
        answer: str = ""
        model_used: str = _local_model_used(services.llm_router, model_profile)
        route = "external" if complexity == "hard" else "local"

        try:
            with trace.step("generate"):
                if complexity == "hard":
                    try:
                        provider = provider_for_model(llm_config.external_model)
                    except ValueError:
                        raise PipelineError(
                            422,
                            f"Configured external model '{llm_config.external_model}' "
                            "is not mapped to a supported provider.",
                        )

                    if provider in SUPPORTED_PROVIDERS and provider not in LIVE_PROVIDERS:
                        raise PipelineError(
                            422,
                            f"Provider '{provider}' is not yet wired to a live client. "
                            "Configure a model from a supported provider (google, openai, anthropic).",
                        )

                    decrypted_key: str | None = None
                    if org_id is not None:
                        try:
                            with get_session() as session:
                                decrypted_key = CredentialService().get_decrypted_key(session, org_id, provider)
                        except ValueError as exc:
                            raise PipelineError(500, str(exc)) from exc
                    if decrypted_key is None:
                        raise PipelineError(
                            402,
                            f"No {provider} API key configured for this organization. "
                            "Add one via the credentials settings.",
                        )

                    ext_request = ExternalLLMRequest(
                        query=user_query,
                        history=history,
                        model=llm_config.external_model,
                        max_tokens=_max_tokens,
                        system_prompt=system_prompt
                        or "You are a helpful assistant. Answer the user's query concisely and accurately.",
                        temperature=temperature or 0.7,
                    )
                    ext_response = await _external_llm.generate_response(
                        ext_request,
                        provider=provider,
                        api_key=decrypted_key,
                    )
                    answer = ext_response.text
                    model_used = ext_response.model_used
                else:
                    llm_system_prompt = (
                        system_prompt
                        or "You are a helpful assistant. Answer the user's query concisely and accurately."
                    )
                    answer, _ = await services.llm_router.generate_local_response(
                        user_query,
                        history=history,
                        max_tokens=_max_tokens,
                        system_prompt=llm_system_prompt,
                    )
                    model_used = _local_model_used(services.llm_router, model_profile)
        except PipelineError:
            raise
        except ExternalLLMError as exc:
            if "not wired to a live client" in str(exc):
                raise PipelineError(422, str(exc)) from exc
            logger.exception("ExternalLLMService failed")
            answer = "I'm sorry, I couldn't process your request right now. Please try again later."
            model_used = "error"
            route = "error"
        except Exception:
            logger.exception("LLM generation failed")
            answer = "I'm sorry, I couldn't process your request right now. Please try again later."
            model_used = "error"
            route = "error"

        # 5. Cache filter + background store
        will_cache = False
        try:
            with trace.step("filter"):
                will_cache, _ = cache_filter.should_cache(enriched, clean_query)
        except Exception:
            logger.exception("Cache filter failed")

        store_status = "skipped"
        miss_response_id: str | None = None
        if will_cache:
            miss_doc_id = _doc_id(clean_query)
            miss_response_id = f"{cache_namespace}:{miss_doc_id}"
            with trace.step("store"):
                if USE_CELERY:
                    try:
                        generalize_and_store_task.apply_async(
                            args=(clean_query, answer, user_query, org_slug, cache_namespace),
                            headers={"dejaq_model_profile": model_profile},
                            ignore_result=True,
                        )
                        store_status = "queued"
                    except Exception as exc:
                        # Broker/result-backend down (e.g. Redis outage): degrade to in-process
                        # storage instead of failing the user-facing chat request.
                        logger.warning("Celery dispatch failed (%s); storing in-process", type(exc).__name__)
                        background_tasks.add_task(
                            _bg_generalize_and_store,
                            clean_query,
                            answer,
                            user_query,
                            org_slug,
                            cache_namespace,
                            model_profile,
                        )
                        store_status = "background-fallback"
                else:
                    background_tasks.add_task(
                        _bg_generalize_and_store,
                        clean_query,
                        answer,
                        user_query,
                        org_slug,
                        cache_namespace,
                        model_profile,
                    )
                    store_status = "background"

        # 6. Build result
        _latency = int((time.monotonic() - _t0) * 1000)
        served_tier: ServedTier = "external" if route == "external" else "local"
        interaction = await _register_answer_interaction(
            org_id=org_id,
            org_slug=org_slug,
            department=dept,
            cache_namespace=cache_namespace,
            served_tier=served_tier,
            response_id=miss_response_id,
            request_messages=list(messages),
        )
        asyncio.create_task(
            request_logger.log(org_slug, dept, _latency, False, complexity, model_used, miss_response_id)
        )
        diff_score = float(classification.get("score", 0.0))
        logger.info(
            "done cache=miss route=%s model=%s store=%s response_id=%s latency=%dms difficulty_score=%.4f steps=%s%s%s",
            route, model_used, store_status, miss_response_id or "none", _latency, diff_score,
            trace.summary(),
            _enriched_log_suffix(enriched, enrich_succeeded),
            _nearest_log_suffix(cache_lookup),
        )

        prompt_tokens = int(len(clean_query.split()) * 1.3)
        completion_tokens = int(len(answer.split()) * 1.3)
        words = answer.split(" ")
        stream_chunks = [w + " " for w in words[:-1]] + [words[-1]] if words else [answer]

        miss_headers: dict[str, str] = {
            "x-dejaq-model-used": model_used,
            "x-dejaq-conversation-id": completion_id,
            "x-dejaq-interaction-id": interaction.interaction_id,
            "x-dejaq-tier": served_tier,
            "x-dejaq-prompt-difficulty": complexity,
            "x-dejaq-prompt-difficulty-score": f"{diff_score:.4f}",
        }
        miss_headers.update(_nearest_headers(cache_lookup))
        if miss_response_id:
            miss_headers["x-dejaq-response-id"] = miss_response_id
        if _validator_verdict is not None:
            miss_headers["x-dejaq-validator-verdict"] = "invalid"

        return ChatPipelineResult(
            answer=answer,
            response_id=miss_response_id,
            completion_id=completion_id,
            model_used=model_used,
            stream_chunks=stream_chunks,
            headers=miss_headers,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
    finally:
        clear_request_id(request_token)


@router.post("/chat/completions")
async def chat_completions(
    oai_request: OAIChatRequest,
    raw_request: Request,
    background_tasks: BackgroundTasks,
):
    try:
        result = await run_chat_pipeline(
            messages=list(oai_request.messages),
            model=oai_request.model,
            temperature=oai_request.temperature,
            max_tokens=oai_request.max_tokens,
            raw_request=raw_request,
            background_tasks=background_tasks,
        )
    except PipelineError as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    if oai_request.stream:
        return StreamingResponse(
            _stream_generator(result.stream_chunks, result.completion_id, oai_request.model, result.model_used),
            media_type="text/event-stream",
            headers=result.headers,
        )

    response = OAIChatResponse(
        id=result.completion_id,
        created=_now_ts(),
        model=oai_request.model,
        choices=[OAIChoice(message=OAIMessageResponse(content=result.answer))],
        usage=OAIUsage(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.prompt_tokens + result.completion_tokens,
        ),
    )
    return JSONResponse(content=response.model_dump(), headers=result.headers)
