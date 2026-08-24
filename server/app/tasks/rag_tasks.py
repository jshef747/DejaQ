import logging

from app.celery_app import celery_app

logger = logging.getLogger("dejaq.tasks.rag")


@celery_app.task(
    name="app.tasks.rag_tasks.ingest_rag_document_task",
    bind=True,
    ignore_result=True,
    max_retries=0,
    queue="background",
    # Overrides the app-wide 180s limit (celery_app.py): embedding a large
    # knowledge-base upload one chunk at a time can legitimately take minutes.
    soft_time_limit=1800,
    time_limit=1860,
)
def ingest_rag_document_task(self, workspace_slug: str, doc_id: int, chunks: list[str]) -> dict:
    """Embed + index a knowledge-base document's chunks in the background.

    The catalog row already exists (status="processing", written synchronously
    by the request that dispatched this task - see rag_admin_service.begin_ingest)
    so this only has to run the slow part. No retries: a Celery retry would
    silently re-embed from scratch while the admin watches a stalled progress
    bar - rag_admin_service.run_ingest already records a clean "failed" with a
    reason on any error, which is more honest than pretending to resume.
    """
    from app.services import rag_admin_service  # lazy: heavy embedder import

    item = rag_admin_service.run_ingest(workspace_slug, doc_id, chunks)
    if item is None:
        return {"status": "failed_or_abandoned", "doc_id": doc_id}
    return {"status": "ready", "doc_id": doc_id, "chunk_count": item.chunk_count}
