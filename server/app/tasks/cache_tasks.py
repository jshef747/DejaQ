import hashlib
import logging
import traceback

import redis as redis_lib

from app.celery_app import celery_app
from app.config import REDIS_URL
from app.services.context_adjuster import ContextAdjusterService
from app.services.memory_chromaDB import MemoryService

logger = logging.getLogger("dejaq.tasks.cache")


def _is_suppressed(clean_query: str) -> bool:
    """Check if negative feedback has flagged this query's storage as suppressed."""
    doc_id = hashlib.sha256(clean_query.encode()).hexdigest()[:16]
    try:
        r = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        return r.exists(f"skip:{doc_id}") == 1
    except redis_lib.exceptions.RedisError:
        return False  # Redis unavailable: proceed with storage

# Lazy-initialized service instances (one per worker process)
_context_adjuster: ContextAdjusterService | None = None
_memory: MemoryService | None = None


def _get_services() -> tuple[ContextAdjusterService, MemoryService]:
    """Lazy-load services on first task execution in this worker process."""
    global _context_adjuster, _memory
    if _context_adjuster is None:
        logger.info("Initializing ContextAdjusterService in worker...")
        _context_adjuster = ContextAdjusterService()
    if _memory is None:
        logger.info("Initializing MemoryService in worker...")
        _memory = MemoryService()
    return _context_adjuster, _memory


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
) -> dict:
    """Generalize an LLM answer (via Phi-3.5) and store in ChromaDB cache.

    All arguments are plain strings — no model objects or unpickleable data.
    """
    if _is_suppressed(clean_query):
        logger.info("Storage suppressed for query '%s'", clean_query[:60])
        return {"status": "suppressed", "clean_query": clean_query}

    try:
        context_adjuster, memory = _get_services()
        generalized = context_adjuster.generalize(answer)
        memory.store_interaction(clean_query, generalized, original_query, user_id)
        logger.info("Task complete: generalized + stored for query '%s'", clean_query[:60])
        return {"status": "stored", "clean_query": clean_query}
    except Exception as exc:
        logger.error("generalize_and_store_task failed: %s", traceback.format_exc())
        raise self.retry(exc=exc)
