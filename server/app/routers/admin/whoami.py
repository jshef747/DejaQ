from fastapi import APIRouter, Depends

from app.dependencies.admin_auth import require_management_auth
from app.dependencies.management_auth import ManagementAuthContext

router = APIRouter()


@router.get("/whoami")
def whoami(ctx: ManagementAuthContext = Depends(require_management_auth)):
    return {
        "authorized": True,
        "actor_type": "system",
        "email": ctx.email,
        "workspaces": [],
    }
