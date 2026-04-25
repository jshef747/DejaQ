import logging

from fastapi import APIRouter, HTTPException, Request

from app.schemas.feedback import FeedbackRequest
from app.services.feedback_service import FeedbackNotFound
from app.services.feedback_service import submit_feedback as submit_feedback_service

logger = logging.getLogger("dejaq.router.feedback")

router = APIRouter()


@router.post("/feedback")
async def submit_feedback(body: FeedbackRequest, raw_request: Request):
    org = getattr(raw_request.state, "org_slug", "anonymous")
    dept = raw_request.headers.get("X-DejaQ-Department") or "default"

    try:
        result = await submit_feedback_service(
            response_id=body.response_id,
            rating=body.rating,
            comment=body.comment,
            org=org,
            department=dept,
            validate_namespace=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FeedbackNotFound as exc:
        raise HTTPException(status_code=404, detail="response_id not found")

    if result.status == "deleted":
        logger.info("First negative feedback — deleted entry %s", body.response_id)
        return {"status": "deleted"}
    return {"status": "ok", "new_score": result.new_score}
