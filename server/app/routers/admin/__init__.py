from fastapi import APIRouter

from app.routers.admin import credentials, departments, feedback, keys, llm_config, orgs, stats, test_provider, whoami

router = APIRouter(prefix="/admin/v1")
router.include_router(whoami.router)
router.include_router(orgs.router)
router.include_router(departments.router)
router.include_router(keys.router)
router.include_router(stats.router)
router.include_router(llm_config.router)
router.include_router(credentials.router)
router.include_router(test_provider.router)
router.include_router(feedback.router)
