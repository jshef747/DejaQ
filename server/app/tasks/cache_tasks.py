import hashlib
import asyncio
import logging
import time

import redis as redis_lib

from app.celery_app import celery_app
from app.config import REDIS_URL, EVICTION_FLOOR
from app.services.context_adjuster import ContextAdjusterService
from app.services.memory_chromaDB import get_memory_service, _pool
from app.services.service_factory import get_context_adjuster_service

logger = logging.getLogger("dejaq.tasks.cache")


def _is_suppressed(clean_query: str) -> bool:
    """Check if negative feedback has flagged this query's storage as suppressed."""
    doc_id = hashlib.sha256(clean_query.encode()).hexdigest()[:16]
    try:
        r = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        return r.exists(f"skip:{doc_id}") == 1
    except redis_lib.exceptions.RedisError:
        return False  # Redis unavailable: proceed with storage

# Lazy-initialized adjuster (one per worker process; MemoryService is pooled per namespace)
_context_adjuster: ContextAdjusterService | None = None
_worker_loop: asyncio.AbstractEventLoop | None = None


def _get_adjuster() -> ContextAdjusterService:
    """Lazy-load ContextAdjusterService on first task execution in this worker process."""
    global _context_adjuster
    if _context_adjuster is None:
        logger.info("Initializing ContextAdjusterService in worker...")
        _context_adjuster = get_context_adjuster_service()
    return _context_adjuster


def _run_async_in_worker(coro):
    """Reuse one event loop per worker process for async backend calls."""
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
    return _worker_loop.run_until_complete(coro)


@celery_app.task(
    name="app.tasks.cache_tasks.generalize_and_store_task",
    bind=True,
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
) -> dict:
    """Generalize an LLM answer (via Phi-3.5) and store in ChromaDB cache.

    All arguments are plain strings — no model objects or unpickleable data.
    cache_namespace selects the ChromaDB collection (department isolation).
    """
    start = time.perf_counter()
    doc_id = hashlib.sha256(clean_query.encode()).hexdigest()[:16]
    if _is_suppressed(clean_query):
        logger.info("cache_store status=suppressed namespace=%s doc_id=%s", cache_namespace, doc_id)
        return {"status": "suppressed", "clean_query": clean_query}

    try:
        context_adjuster = _get_adjuster()
        memory = get_memory_service(cache_namespace)
        generalized = _run_async_in_worker(context_adjuster.generalize(answer))
        doc_id = memory.store_interaction(clean_query, generalized, original_query, user_id)
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
    """Scan all active ChromaDB namespaces and delete entries below EVICTION_FLOOR."""
    total_deleted = 0
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
