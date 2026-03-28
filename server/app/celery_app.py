from celery import Celery
from app.config import REDIS_URL

celery_app = Celery(
    "dejaq",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    # Task autodiscovery
    include=["app.tasks.cache_tasks"],

    # Queue routing
    task_routes={
        "app.tasks.cache_tasks.generalize_and_store_task": {"queue": "background"},
    },

    # Concurrency control — don't prefetch extra tasks during slow inference
    worker_prefetch_multiplier=1,

    # Serialization — JSON only (model objects aren't pickleable)
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Task behavior
    task_acks_late=True,
    task_reject_on_worker_lost=False,  # Don't re-queue on worker crash (prevents infinite loops)
    task_track_started=True,

    # Result expiry (fire-and-forget, but keep briefly for debugging)
    result_expires=3600,

    # Timeouts
    task_soft_time_limit=120,
    task_time_limit=180,
)
