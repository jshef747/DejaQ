import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.db import dept_repo
from app.db.session import get_session
from app.dependencies.auth import ResolvedWorkspace, require_org_key

logger = logging.getLogger("dejaq.router.departments")

router = APIRouter()


class DepartmentItem(BaseModel):
    id: int
    label: str
    slug: str


@router.get("/departments", response_model=list[DepartmentItem])
def get_departments(workspace: ResolvedWorkspace = Depends(require_org_key)) -> list[DepartmentItem]:
    """Return the departments belonging to the authenticated workspace.

    Authorization: Bearer <workspace-api-key>
    """
    with get_session() as session:
        depts = dept_repo.list_depts(session, workspace_slug=workspace.workspace_slug)

    logger.info("GET /departments workspace=%s count=%d", workspace.workspace_slug, len(depts))
    return [DepartmentItem(id=d.id, label=d.name, slug=d.slug) for d in depts]
