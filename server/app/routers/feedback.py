import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from app.schemas.feedback import FeedbackRequest
from app.services.memory_chromaDB import get_memory_service
from app.services.request_logger import request_logger

logger = logging.getLogger("dejaq.router.feedback")

router = APIRouter()


@router.post("/feedback")
async def submit_feedback(body: FeedbackRequest, raw_request: Request):
    # Parse response_id into namespace + doc_id
    if ":" not in body.response_id:
        raise HTTPException(status_code=422, detail="Invalid response_id format; expected <namespace>:<doc_id>")
    namespace, doc_id = body.response_id.split(":", 1)

    org = getattr(raw_request.state, "org_slug", "anonymous")
    dept = raw_request.headers.get("X-DejaQ-Department") or "default"

    # Log feedback fire-and-forget
    asyncio.create_task(
        request_logger.log_feedback(body.response_id, org, dept, body.rating, body.comment)
    )

    memory = get_memory_service(namespace)

    try:
        if body.rating == "negative":
            neg_count = memory.get_negative_count(doc_id)
            if neg_count == 0:
                memory.delete_entry(doc_id)
                logger.info("First negative feedback — deleted entry %s (namespace=%s)", doc_id, namespace)
                return {"status": "deleted"}
            else:
                new_score = memory.update_score(doc_id, -2.0)
                return {"status": "ok", "new_score": new_score}
        else:
            new_score = memory.update_score(doc_id, 1.0)
            return {"status": "ok", "new_score": new_score}
    except KeyError:
        raise HTTPException(status_code=404, detail="response_id not found")
