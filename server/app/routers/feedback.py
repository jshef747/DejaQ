import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies.auth import ResolvedOrg, require_org_key
from app.schemas.feedback import FeedbackRequest
from app.services.feedback_service import FeedbackNotFound
from app.services.feedback_service import submit_feedback as submit_feedback_service

logger = logging.getLogger("dejaq.router.feedback")

router = APIRouter()


@router.post("/feedback")
async def submit_feedback(
    body: FeedbackRequest,
    raw_request: Request,
    resolved_org: ResolvedOrg = Depends(require_org_key),
):
    org = resolved_org.org_slug
    org_id = resolved_org.org_id
    dept = raw_request.headers.get("X-DejaQ-Department") or "default"

    try:
        result = await submit_feedback_service(
            response_id=body.response_id,
            interaction_id=body.interaction_id,
            messages=body.messages,
            rating=body.rating,
            comment=body.comment,
            org=org,
            org_id=org_id,
            department=dept,
            validate_namespace=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FeedbackNotFound as exc:
        raise HTTPException(status_code=404, detail="response_id not found")

    has_escalation_fields = result.escalation_status is not None or result.escalated_response is not None
    if result.status == "deleted" and not has_escalation_fields:
        logger.info("First negative feedback — deleted entry %s", body.response_id)
        return {"status": "deleted"}
    if not has_escalation_fields:
        return {"status": "ok", "new_score": result.new_score}
    payload = result.model_dump(exclude_none=True)
    return payload
