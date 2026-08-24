import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies.auth import ResolvedWorkspace, require_org_key
from app.schemas.feedback import FeedbackRequest
from app.services.feedback_service import FeedbackNamespaceMismatch, FeedbackNotFound
from app.services.feedback_service import submit_feedback as submit_feedback_service

logger = logging.getLogger("dejaq.router.feedback")

router = APIRouter()


@router.post("/feedback")
async def submit_feedback(
    body: FeedbackRequest,
    raw_request: Request,
    resolved_workspace: ResolvedWorkspace = Depends(require_org_key),
):
    workspace = resolved_workspace.workspace_slug
    workspace_id = resolved_workspace.workspace_id
    dept = raw_request.headers.get("X-DejaQ-Department") or "default"
    # The namespace the write path used, resolved from the departments table by
    # ApiKeyMiddleware. Deriving it again from the slugs sent a workspace whose
    # department is named "Default" to `<workspace>--default` while its entries
    # live in `<workspace>__default`.
    cache_namespace = getattr(raw_request.state, "cache_namespace", None)

    try:
        result = await submit_feedback_service(
            response_id=body.response_id,
            interaction_id=body.interaction_id,
            messages=body.messages,
            edited_answer=body.edited_answer,
            chosen_draft_response_id=body.chosen_draft_response_id,
            rejected_draft_response_ids=body.rejected_draft_response_ids,
            rating=body.rating,
            comment=body.comment,
            workspace=workspace,
            workspace_id=workspace_id,
            department=dept,
            validate_namespace=True,
            cache_namespace=cache_namespace,
        )
    except FeedbackNamespaceMismatch as exc:
        # Subclasses neither ValueError nor FeedbackNotFound, so without this it
        # left the router as an uncaught 500. It is a caller error: the
        # response_id belongs to another workspace or department.
        raise HTTPException(
            status_code=422,
            detail="response_id does not belong to this workspace/department",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FeedbackNotFound as exc:
        raise HTTPException(status_code=404, detail="response_id not found") from exc

    has_escalation_fields = result.escalation_status is not None or result.escalated_response is not None
    # An edit carries its own fields back, so it must not take either of the
    # two legacy shortcuts below - both drop everything except status/new_score.
    has_extra_fields = (
        has_escalation_fields
        or result.edit_status is not None
        or result.draft_choice is not None
    )
    if result.status == "deleted" and not has_extra_fields:
        logger.info("First negative feedback — deleted entry %s", body.response_id)
        return {"status": "deleted"}
    if not has_extra_fields:
        return {"status": "ok", "new_score": result.new_score}
    payload = result.model_dump(exclude_none=True)
    return payload
