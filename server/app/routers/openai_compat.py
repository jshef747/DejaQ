# server/app/routers/openai_compat.py
import asyncio
import base64
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, Depends, Request
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
from app.services.image_fingerprint import (
    ImageFingerprint,
    fingerprint as compute_image_fingerprint,
    gate_result as image_gate_result,
)
from app.services.image_text import (
    OcrResult,
    extract as extract_image_text,
    matches as text_matches,
    tokens_from_string,
)
from app.dependencies.auth import ResolvedWorkspace, require_org_key
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
from app.config import (
    CACHE_ALIAS_ENABLED,
    CACHE_IMAGE_OCR_ENABLED,
    EXTERNAL_MODEL_NAME,
    ROUTING_THRESHOLD,
    USE_CELERY,
    VALIDATOR_SKIP_DISTANCE,
)
from app.db.session import get_session
from app.utils.exceptions import ExternalLLMError
from app.utils.logger import clear_request_id, content_snippet, hide_content, set_request_id
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


def _read_effective_llm_config(workspace_slug: str, workspace_id: int | None) -> EffectiveLlmConfig:
    if workspace_id is None:
        return EffectiveLlmConfig(
            external_model=EXTERNAL_MODEL_NAME,
            routing_threshold=ROUTING_THRESHOLD,
        )
    try:
        config = llm_config_service.read_for_workspace(workspace_slug)
    except llm_config_service.WorkspaceNotFound:
        logger.warning("LLM config requested for missing org slug=%s; using defaults", workspace_slug)
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


def _fmt_opt(value, fmt: str) -> str:
    return fmt.format(value) if value is not None else "n/a"


def _image_kind(ocr: OcrResult | None) -> str:
    """Which gate applies: its words, its pixels, or neither.

    "ambiguous" means OCR found real text but not enough to compare by words.
    Such an image is never served and never stored — routing it to the pixel gate
    instead was the largest measured source of wrong answers (docs/image-gate.md).
    No entry is ever written with this kind, so the gate's kind check rejects it
    without needing a special case.
    """
    if ocr and ocr.is_document:
        return "document"
    if ocr and ocr.is_ambiguous:
        return "ambiguous"
    return "photo"


def _entry_image_kind(lookup: CacheLookupResult) -> str:
    """Kind of the matched cache entry — "text" when it carries no image.

    Falls back to inspecting the stored fingerprints so entries written before
    image_kind existed still classify correctly.
    """
    if lookup.image_kind:
        return lookup.image_kind
    if lookup.image_text:
        return "document"
    if lookup.image_dhash and lookup.image_clip:
        return "photo"
    return "text"


def _evaluate_image_gate(
    *,
    request_kind: str,
    entry_kind: str,
    fingerprint: ImageFingerprint | None,
    ocr: OcrResult | None,
    lookup: CacheLookupResult,
) -> tuple[bool, str, dict]:
    """Decide whether a cached image entry may be served. Returns (ok, reason, metrics).

    Kinds must match first: a photo must never be served a document's answer (or
    a text-only entry's), because their fingerprints are not comparable at all.
    """
    if request_kind != entry_kind:
        return False, f"kind_mismatch_{request_kind}_vs_{entry_kind}", {}

    if request_kind == "document":
        if ocr is None:
            return False, "ocr_unavailable", {}
        match = text_matches(ocr.tokens, tokens_from_string(lookup.image_text))
        return (
            match.matched,
            "text_pass" if match.matched else "text_mismatch",
            {"token_jaccard": match.token_jaccard},
        )

    if fingerprint is None:
        return False, "fingerprint_failed", {}
    gate = image_gate_result(fingerprint, lookup.image_dhash, lookup.image_clip)
    return gate.passed, gate.reason, {"clip_distance": gate.clip_distance, "hamming": gate.hamming}


def _image_log_suffix(
    has_image: bool,
    clip_distance: float | None,
    hamming: int | None,
    token_jaccard: float | None,
) -> str:
    """Trailing image metrics for the per-request `done` summary line.

    Empty for text-only requests; otherwise reports whichever gate ran (pixel
    metrics for photos, token overlap for documents)."""
    if not has_image:
        return ""
    return (
        f" image=true image_clip_distance={_fmt_opt(clip_distance, '{:.4f}')}"
        f" image_hamming={_fmt_opt(hamming, '{}')}"
        f" image_token_jaccard={_fmt_opt(token_jaccard, '{:.3f}')}"
    )


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
    image_dhash: str | None = None,
    image_clip: str | None = None,
    image_kind: str | None = None,
    image_text: str | None = None,
) -> None:
    start = time.perf_counter()
    doc_id = _doc_id(clean_query)
    try:
        # Image-anchored answers are stored verbatim — see the note in
        # tasks/cache_tasks.py: generalization cannot see the image and invents
        # specifics, and the image gate already pins the answer to one image.
        if image_kind:
            generalized = answer
        else:
            generalized = asyncio.run(_services_for_model_profile(model_profile).adjuster.generalize(answer))
        memory = get_memory_service(cache_namespace)
        doc_id = memory.store_interaction(
            clean_query, generalized, original_query, tenant_id,
            image_dhash=image_dhash, image_clip=image_clip,
            image_kind=image_kind, image_text=image_text,
        )
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


async def _store_alias_bg(namespace: str, alias_query: str, source_entry_id: str) -> None:
    try:
        memory = get_memory_service(namespace)
        store_alias = getattr(memory, "store_alias", None)
        if callable(store_alias):
            await asyncio.to_thread(store_alias, alias_query, source_entry_id)
    except Exception:
        logger.warning("Failed to store alias for %s:%s", namespace, source_entry_id)


async def _register_answer_interaction(
    *,
    workspace_id: int | None,
    workspace_slug: str,
    department: str,
    cache_namespace: str,
    served_tier: ServedTier,
    response_id: str | None,
    request_messages: list[object],
) -> ResponseInteraction:
    try:
        return await response_registry.register(
            workspace_id=workspace_id,
            workspace_slug=workspace_slug,
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
            workspace_id=workspace_id,
            workspace_slug=workspace_slug,
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
    image: tuple[bytes, str] | None = None,
) -> ChatPipelineResult:
    """Core DejaQ pipeline: enrich → normalize → cache → validate → adjust/generate → store.

    `image` is (bytes, mime) for an image request; None for text. Image requests
    are gated on BOTH CLIP distance and dHash before a cache hit is served, and
    always routed to the (vision-capable) external provider on a miss.

    Raises PipelineError for HTTP-level failures (400, 402, 422, 500).
    """
    image_bytes, image_mime = image if image else (None, None)
    _request_has_image = image_bytes is not None
    image_fp: ImageFingerprint | None = None
    image_ocr: OcrResult | None = None
    _t0 = time.monotonic()
    trace = PipelineTrace()
    cache_namespace: str = getattr(raw_request.state, "cache_namespace", "dejaq_default")
    workspace_slug: str = getattr(raw_request.state, "workspace_slug", "anonymous")
    workspace_id: int | None = getattr(raw_request.state, "workspace_id", None)
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
    llm_config = await run_in_threadpool(_read_effective_llm_config, workspace_slug, workspace_id)
    services = _services_for_model_profile(model_profile)

    try:
        query = content_snippet(user_query)
        if query:
            logger.info(
                "start org=%s dept=%s namespace=%s model=%s query=%s",
                workspace_slug, dept, cache_namespace, model, query,
            )
        else:
            logger.info(
                "start org=%s dept=%s namespace=%s model=%s",
                workspace_slug, dept, cache_namespace, model,
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

        # Fingerprint the image once — used both to gate a hit and to store on a
        # miss. Two kinds, compared by completely different means:
        #   document (OCR found confident text) -> compared by its words
        #   photo    (everything else)          -> compared by CLIP + dHash
        # Pixel similarity is actively wrong for documents: two DIFFERENT syllabi
        # on one template measured CLIP 0.027 / hamming 0 while two screenshots of
        # the SAME syllabus measured hamming 10-19. See docs/image-gate.md.
        _image_clip_distance: float | None = None
        _image_hamming: int | None = None
        _image_token_jaccard: float | None = None
        _image_gate_logged = False
        _image_anchored = False  # the gate accepted: this hit is pinned to one image
        if _request_has_image:
            if CACHE_IMAGE_OCR_ENABLED:
                try:
                    with trace.step("image_ocr"):
                        image_ocr = await run_in_threadpool(extract_image_text, image_bytes)
                except Exception:
                    logger.exception("OCR failed; treating image as a photo")
            # Only photos need a pixel fingerprint. Documents are compared by
            # words, and ambiguous images are not cacheable at all — computing one
            # for them is what used to let them merge with unrelated pages.
            if _image_kind(image_ocr) == "photo":
                try:
                    with trace.step("image_fp"):
                        image_fp = await run_in_threadpool(compute_image_fingerprint, image_bytes)
                except Exception:
                    logger.exception("Image fingerprint failed; image treated as un-cacheable")
            logger.info(
                "image_request attached=true bytes=%d mime=%s kind=%s ocr_words=%d "
                "ocr_confidence=%.1f dhash=%s query=%s",
                len(image_bytes),
                image_mime or "?",
                _image_kind(image_ocr),
                image_ocr.word_count if image_ocr else 0,
                image_ocr.mean_confidence if image_ocr else 0.0,
                image_fp.dhash_hex if image_fp else "none",
                hide_content(user_query),
            )

        # Image gate. Kinds must agree (a photo never matches a document entry,
        # and a text request never matches either), then the matching kind's rule
        # decides.
        if cache_lookup.hit:
            _entry_kind = _entry_image_kind(cache_lookup)
            _request_kind = _image_kind(image_ocr) if _request_has_image else "text"
            if _request_has_image or _entry_kind != "text":
                verdict, reason, detail = _evaluate_image_gate(
                    request_kind=_request_kind,
                    entry_kind=_entry_kind,
                    fingerprint=image_fp,
                    ocr=image_ocr,
                    lookup=cache_lookup,
                )
                _image_clip_distance = detail.get("clip_distance")
                _image_hamming = detail.get("hamming")
                _image_token_jaccard = detail.get("token_jaccard")
                _image_gate_logged = True
                logger.info(
                    "image_gate verdict=%s request_kind=%s entry_kind=%s reason=%s "
                    "clip_distance=%s hamming=%s token_jaccard=%s "
                    "matched_entry=%s matched_query=%s",
                    "accept" if verdict else "reject",
                    _request_kind, _entry_kind, reason,
                    _fmt_opt(detail.get("clip_distance"), "{:.4f}"),
                    _fmt_opt(detail.get("hamming"), "{}"),
                    _fmt_opt(detail.get("token_jaccard"), "{:.3f}"),
                    cache_lookup.entry_id or "?",
                    _diagnostic_prompt(cache_lookup.matched_query) or "",
                )
                if not verdict:
                    cache_lookup = CacheLookupResult(
                        hit=False,
                        nearest_distance=cache_lookup.distance,
                        nearest_prompt=cache_lookup.matched_query,
                    )
                else:
                    _image_anchored = _request_has_image

        # Image request that never reached a cache hit to gate against — record
        # how close the text landed so the log still shows the image outcome.
        if _request_has_image and not _image_gate_logged:
            logger.info(
                "image_gate verdict=miss kind=%s reason=no_cached_image nearest_text_distance=%s query=%s",
                _image_kind(image_ocr),
                f"{cache_lookup.nearest_distance:.4f}" if cache_lookup.nearest_distance is not None else "n/a",
                hide_content(user_query),
            )

        _validator_verdict: str | None = None
        if cache_lookup.hit:
            cached_answer = cache_lookup.generalized_answer or ""
            _entry_id = cache_lookup.entry_id or ""
            _cache_distance = float(cache_lookup.distance or 0.0)
            _cache_matched_query = _diagnostic_prompt(cache_lookup.matched_query) or ""

            _requires_validation = bool(getattr(cache_lookup, "requires_validation", False))
            _validator_accepted = True
            # Near-identical matches (cosine distance ≤ VALIDATOR_SKIP_DISTANCE) don't
            # need validation — the embedding already guarantees the cached answer covers
            # the question. Calling the validator here would only burn latency and risk
            # an over-rejection on a clearly correct hit. Band hits (requires_validation)
            # never skip: they are only trustworthy once the validator accepts them.
            _skip_validation = (not _requires_validation) and _cache_distance <= VALIDATOR_SKIP_DISTANCE
            if not _skip_validation:
                # Word-swap hint from the lexical gate ("'list' vs 'string'") —
                # sharpens the validator on near-identical sibling questions.
                _mismatches = getattr(cache_lookup, "mismatches", None)
                _hint = (
                    ", ".join(f"'{a}' vs '{b}'" for a, b in _mismatches)
                    if _mismatches else None
                )
                try:
                    with trace.step("validate"):
                        try:
                            _validator_accepted, _validator_verdict = await services.validator.validate(
                                user_query,
                                cache_lookup.matched_query or "",
                                cached_answer,
                                mismatch_hint=_hint,
                                # Only sent when set: the TypeError fallback below
                                # drops the hint, so text calls must stay unchanged
                                # for validators that predate this kwarg.
                                **({"image_anchored": True} if _image_anchored else {}),
                            )
                        except TypeError:
                            # Stub/legacy validator without the mismatch_hint kwarg
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
                    "validator rejected cache hit mode=%s distance=%.4f matched_query=%r steps=%s",
                    "image" if _image_anchored else "text",
                    _cache_distance, _cache_matched_query, trace.summary(),
                )
            else:
                if _image_anchored:
                    # Image answers are stored verbatim (the generalizer invents
                    # specifics it cannot see — docs/image-gate.md), so no tone was
                    # ever stripped and there is nothing to put back. Running the
                    # adjuster here would be the same blind rewrite, plus ~2.1s.
                    answer = cached_answer
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
                    workspace_id=workspace_id,
                    workspace_slug=workspace_slug,
                    department=dept,
                    cache_namespace=cache_namespace,
                    served_tier="cache",
                    response_id=response_id,
                    request_messages=list(messages),
                )
                _latency = int((time.monotonic() - _t0) * 1000)
                asyncio.create_task(request_logger.log(workspace_slug, dept, _latency, True, None, None, response_id))
                asyncio.create_task(_increment_hit_count_bg(cache_namespace, _entry_id))
                # Alias learning: the validator vouched for this band/rescue hit,
                # so remember the typo'd phrasing — next time it's a trusted hit.
                if _requires_validation and CACHE_ALIAS_ENABLED:
                    asyncio.create_task(_store_alias_bg(cache_namespace, clean_query, _entry_id))
                logger.info(
                    "done cache=hit route=cache model=%s response_id=%s latency=%dms band=%s rescued=%s steps=%s%s%s%s",
                    model_used, response_id, _latency,
                    _requires_validation, bool(getattr(cache_lookup, "rescued", False)),
                    trace.summary(),
                    _enriched_log_suffix(enriched, enrich_succeeded),
                    _nearest_log_suffix(cache_lookup),
                    _image_log_suffix(_request_has_image, _image_clip_distance, _image_hamming, _image_token_jaccard),
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
        if _request_has_image:
            # The local model is text-only; image queries must go to a vision-capable
            # external provider regardless of difficulty or routing mode.
            classification = {"complexity": "hard", "score": 1.0, "task_type": "image_external"}
        elif routing_mode == ROUTING_MODE_EASY_LOCAL:
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
                    if workspace_id is not None:
                        try:
                            with get_session() as session:
                                decrypted_key = CredentialService().get_decrypted_key(session, workspace_id, provider)
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
                        image_b64=base64.b64encode(image_bytes).decode("ascii") if _request_has_image else None,
                        image_mime=image_mime,
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
                will_cache, _ = cache_filter.should_cache(
                    enriched, clean_query, has_image=_request_has_image
                )
        except Exception:
            logger.exception("Cache filter failed")

        # Never cache a failed generation. Without this the user-facing apology
        # ("I'm sorry, I couldn't process your request…") is stored as a real
        # answer and served to every later match — observed live.
        if route == "error":
            will_cache = False
            logger.warning("generation failed; not caching the error response")

        # An image with no usable fingerprint of either kind can't be gated on
        # future hits, so don't cache it — the query text alone would wrongly
        # match a plain text ask later. This now also covers the two cases that
        # used to reach the pixel gate and merge with unrelated documents: an
        # "ambiguous" image (real text, below the document bar) gets no
        # fingerprint computed, and a near-uniform one gets None back.
        _img_kind = _image_kind(image_ocr) if _request_has_image else None
        _img_text = image_ocr.token_string() if (image_ocr and image_ocr.is_document) else None
        _img_dhash = image_fp.dhash_hex if image_fp else None
        _img_clip = image_fp.clip_b64 if image_fp else None
        if _request_has_image and not _img_text and not (_img_dhash and _img_clip):
            will_cache = False
            logger.info("image not cacheable kind=%s; answer will not be stored", _img_kind)

        store_status = "skipped"
        miss_response_id: str | None = None
        if will_cache:
            miss_doc_id = _doc_id(clean_query)
            miss_response_id = f"{cache_namespace}:{miss_doc_id}"
            with trace.step("store"):
                if USE_CELERY:
                    try:
                        # Text requests keep the legacy positional-args call; image
                        # fingerprints ride as kwargs only when present.
                        _apply_kwargs: dict = {
                            "headers": {"dejaq_model_profile": model_profile},
                            "ignore_result": True,
                        }
                        if _request_has_image:
                            _apply_kwargs["kwargs"] = {
                                "image_dhash": _img_dhash, "image_clip": _img_clip,
                                "image_kind": _img_kind, "image_text": _img_text,
                            }
                        generalize_and_store_task.apply_async(
                            args=(clean_query, answer, user_query, workspace_slug, cache_namespace),
                            **_apply_kwargs,
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
                            workspace_slug,
                            cache_namespace,
                            model_profile,
                            _img_dhash,
                            _img_clip,
                            _img_kind,
                            _img_text,
                        )
                        store_status = "background-fallback"
                else:
                    background_tasks.add_task(
                        _bg_generalize_and_store,
                        clean_query,
                        answer,
                        user_query,
                        workspace_slug,
                        cache_namespace,
                        model_profile,
                        _img_dhash,
                        _img_clip,
                        _img_kind,
                        _img_text,
                    )
                    store_status = "background"

        # 6. Build result
        _latency = int((time.monotonic() - _t0) * 1000)
        served_tier: ServedTier = "external" if route == "external" else "local"
        interaction = await _register_answer_interaction(
            workspace_id=workspace_id,
            workspace_slug=workspace_slug,
            department=dept,
            cache_namespace=cache_namespace,
            served_tier=served_tier,
            response_id=miss_response_id,
            request_messages=list(messages),
        )
        asyncio.create_task(
            request_logger.log(workspace_slug, dept, _latency, False, complexity, model_used, miss_response_id)
        )
        diff_score = float(classification.get("score", 0.0))
        logger.info(
            "done cache=miss route=%s model=%s store=%s response_id=%s latency=%dms difficulty_score=%.4f steps=%s%s%s%s",
            route, model_used, store_status, miss_response_id or "none", _latency, diff_score,
            trace.summary(),
            _enriched_log_suffix(enriched, enrich_succeeded),
            _nearest_log_suffix(cache_lookup),
            _image_log_suffix(_request_has_image, _image_clip_distance, _image_hamming, _image_token_jaccard),
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
    resolved_workspace: ResolvedWorkspace = Depends(require_org_key),
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
