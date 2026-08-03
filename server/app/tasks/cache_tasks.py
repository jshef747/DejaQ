import hashlib
import asyncio
import logging
import time

import redis as redis_lib

from app.celery_app import celery_app
from app.config import REDIS_URL, EVICTION_FLOOR
from app.services.context_adjuster import ContextAdjusterService
from app.services.memory_chromaDB import derive_doc_id, get_memory_service, list_namespaces, _pool
from app.services.service_factory import get_context_adjuster_service

logger = logging.getLogger("dejaq.tasks.cache")

# Bound, not reimplemented — this id must match the router's and the store's.
_doc_id = derive_doc_id


def _is_suppressed(clean_query: str) -> bool:
    """Check if negative feedback has flagged this query's storage as suppressed."""
    doc_id = hashlib.sha256(clean_query.encode()).hexdigest()[:16]
    try:
        r = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        return r.exists(f"skip:{doc_id}") == 1
    except redis_lib.exceptions.RedisError:
        return False  # Redis unavailable: proceed with storage

# Lazy-initialized adjuster (one per worker process; MemoryService is pooled per namespace)
_context_adjusters: dict[str, ContextAdjusterService] = {}
_worker_loop: asyncio.AbstractEventLoop | None = None


def _get_adjuster(model_profile: str = "default") -> ContextAdjusterService:
    """Lazy-load ContextAdjusterService on first task execution in this worker process."""
    if model_profile not in _context_adjusters:
        logger.info("Initializing ContextAdjusterService in worker profile=%s...", model_profile)
        if model_profile == "weak_cpu":
            _context_adjusters[model_profile] = get_context_adjuster_service(
                adjust_model_name="qwen_0_5b",
                generalize_model_name="qwen_0_5b",
            )
        else:
            _context_adjusters[model_profile] = get_context_adjuster_service()
    return _context_adjusters[model_profile]


def _run_async_in_worker(coro):
    """Reuse one event loop per worker process for async backend calls."""
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
    return _worker_loop.run_until_complete(coro)


@celery_app.task(
    name="app.tasks.cache_tasks.generalize_and_store_task",
    bind=True,
    ignore_result=True,  # fire-and-forget: don't subscribe to the result backend on dispatch
    max_retries=2,
    default_retry_delay=5,
    queue="background",
)
def generalize_and_store_task(
    self,
    clean_query: str,
    answer: str,
    original_query: str,
    user_id: str,
    cache_namespace: str = "dejaq_default",
    model_profile: str = "default",
    image_dhash: str | None = None,
    image_clip: str | None = None,
    image_kind: str | None = None,
    image_text: str | None = None,
    file_sha: str | None = None,
    file_kind: str | None = None,
) -> dict:
    """Generalize an LLM answer (via Phi-3.5) and store in ChromaDB cache.

    All arguments are plain strings — no model objects or unpickleable data.
    cache_namespace selects the ChromaDB collection (department isolation).
    The image_* args are the scalar fingerprints for image requests (all None
    for text): photos carry dhash+clip, documents carry OCR tokens in image_text.
    The file_* args are the exact identity of an attached PDF/Markdown file.
    """
    start = time.perf_counter()
    doc_id = _doc_id(clean_query, file_sha, image_text=image_text, image_dhash=image_dhash)
    if _is_suppressed(clean_query):
        logger.info("cache_store status=suppressed namespace=%s doc_id=%s", cache_namespace, doc_id)
        return {"status": "suppressed", "clean_query": clean_query}

    try:
        headers = getattr(self.request, "headers", None) or {}
        resolved_model_profile = headers.get("dejaq_model_profile") or model_profile
        memory = get_memory_service(cache_namespace)
        # Attachment-anchored answers are stored verbatim. Generalization strips
        # tone so a TEXT answer survives rephrasing, but it only sees the answer —
        # never the image or the file — so on attachment answers it invents
        # specifics instead (observed live: a Complex Analysis syllabus was stored
        # as "Statistics or Data Analysis Course"). The gate already guarantees
        # the same attachment, so there is nothing to generalize across and the
        # rewrite is pure risk.
        if image_kind or file_kind:
            generalized = answer
        else:
            context_adjuster = _get_adjuster(resolved_model_profile)
            generalized = _run_async_in_worker(context_adjuster.generalize(answer))
        doc_id = memory.store_interaction(
            clean_query, generalized, original_query, user_id,
            image_dhash=image_dhash, image_clip=image_clip,
            image_kind=image_kind, image_text=image_text,
            file_sha=file_sha, file_kind=file_kind,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "cache_store status=stored namespace=%s doc_id=%s latency=%dms",
            cache_namespace,
            doc_id,
            latency_ms,
        )
        return {"status": "stored", "clean_query": clean_query, "namespace": cache_namespace, "doc_id": doc_id}
    except Exception as exc:
        logger.exception("cache_store status=failed namespace=%s doc_id=%s", cache_namespace, doc_id)
        raise self.retry(exc=exc)


@celery_app.task(
    name="app.tasks.cache_tasks.evict_low_score_entries",
    queue="background",
)
def evict_low_score_entries() -> dict:
    """Scan every ChromaDB namespace and delete entries below EVICTION_FLOOR.

    Namespaces come from ChromaDB, not from this worker's `_pool`. The pool only
    holds namespaces this process has served since it started, so a beat task
    reading it swept nothing after a restart and never touched a department whose
    traffic went to a different worker - the entries a score floor exists to
    remove are exactly the ones nobody is asking for.
    """
    total_deleted = 0
    try:
        namespaces = list_namespaces()
    except Exception:
        # Sweeping what this worker knows about is worse than sweeping
        # everything, and better than sweeping nothing.
        logger.error(
            "Could not list ChromaDB namespaces; falling back to this worker's pool",
            exc_info=True,
        )
        namespaces = list(_pool.keys())
    for namespace in namespaces:
        try:
            memory = get_memory_service(namespace)
            deleted = memory.evict_below_floor(EVICTION_FLOOR)
            total_deleted += deleted
        except Exception:
            logger.error("Eviction failed for namespace '%s'", namespace, exc_info=True)
    logger.info("Eviction run complete: %d total entries removed (floor=%.1f)", total_deleted, EVICTION_FLOOR)
    return {"status": "ok", "deleted": total_deleted}
