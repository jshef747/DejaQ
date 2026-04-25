from fastapi import APIRouter, Depends

from app.dependencies.admin_auth import require_admin_token
from app.routers.admin import departments, feedback, keys, llm_config, orgs, stats, whoami

router = APIRouter(
    prefix="/admin/v1",
    dependencies=[Depends(require_admin_token)],
)
router.include_router(whoami.router)
router.include_router(orgs.router)
router.include_router(departments.router)
router.include_router(keys.router)
router.include_router(stats.router)
router.include_router(llm_config.router)
router.include_router(feedback.router)
