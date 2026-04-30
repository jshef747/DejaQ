import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies.admin_auth import require_management_auth
from app.dependencies.management_auth import ManagementAuthContext
from app.schemas.admin.feedback import AdminFeedbackRequest, FeedbackListResponse
from app.services import admin_service, feedback_service

router = APIRouter()


@router.get("/feedback", response_model=FeedbackListResponse)
def list_feedback(
    org: str | None = None,
    department: str | None = None,
    response_id: str | None = None,
    limit: int = Query(default=100, le=500, ge=0),
    offset: int = Query(default=0, ge=0),
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    accessible_slugs = None if ctx.is_system else {o.slug for o in ctx.accessible_orgs}
    if not ctx.is_system and org and (accessible_slugs is not None and org not in accessible_slugs):
        raise HTTPException(status_code=403, detail=f"Access denied to organization '{org}'.")

    return feedback_service.list_feedback(
        org=org,
        department=department,
        response_id=response_id,
        limit=limit,
        offset=offset,
        accessible_org_slugs=accessible_slugs,
    )


@router.post("/feedback")
async def submit_feedback(
    body: AdminFeedbackRequest,
    ctx: ManagementAuthContext = Depends(require_management_auth),
):
    if body.org and not ctx.has_org_access_by_slug(body.org):
        raise HTTPException(status_code=403, detail=f"Access denied to organization '{body.org}'.")

    try:
        depts = await asyncio.to_thread(admin_service.list_departments, org_slug=body.org, ctx=ctx)
        if body.department != "default" and all(dept.slug != body.department for dept in depts):
            raise feedback_service.FeedbackDeptNotFound(body.department)
        result = await feedback_service.submit_feedback(
            response_id=body.response_id,
            rating=body.rating,
            comment=body.comment,
            org=body.org,
            department=body.department,
            validate_namespace=True,
        )
    except admin_service.OrgNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except admin_service.OrgForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except feedback_service.FeedbackDeptNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except feedback_service.FeedbackNamespaceMismatch as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except feedback_service.FeedbackNotFound as exc:
        raise HTTPException(status_code=404, detail="response_id not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if result.status == "deleted":
        return {"status": "deleted"}
    return {"status": "ok", "new_score": result.new_score}
