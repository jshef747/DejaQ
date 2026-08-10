from fastapi import APIRouter, Depends

from app.dependencies.admin_auth import require_management_auth
from app.dependencies.management_auth import ManagementAuthContext

router = APIRouter()


@router.get("/whoami")
def whoami(ctx: ManagementAuthContext = Depends(require_management_auth)):
    return {
        "authorized": True,
        "actor_type": ctx.actor_type,
        "supabase_user_id": ctx.supabase_user_id,
        "email": ctx.email,
        "workspaces": [
            {
                "id": ws.id,
                "name": ws.name,
                "slug": ws.slug,
                "created_at": ws.created_at,
            }
            for ws in ctx.accessible_workspaces
        ],
    }
