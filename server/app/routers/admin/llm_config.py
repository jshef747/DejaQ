from fastapi import APIRouter, HTTPException

from app.schemas.admin.llm_config import LlmConfigResponse, LlmConfigUpdate
from app.services import llm_config_service, ollama_catalog, pipeline_config_cache

router = APIRouter()


def _with_vision_capability(result: llm_config_service.LlmConfigResult) -> dict:
    # Enriched at the router, not inside llm_config_service.LlmConfigResult:
    # these are display-only fields for this one admin response, not part of
    # the effective pipeline config other callers (openai_compat,
    # pipeline_config_cache, the Celery task) resolve.
    external_provider = result.external_provider
    if external_provider is None and result.external_model is not None:
        # A row written before the external_provider column existed (see
        # llm_config_service.read_for_workspace's own null-provider test):
        # the service deliberately leaves this unguessed for every other
        # caller, but the dashboard's provider combobox needs *something* to
        # preselect on reload, so derive it here from the qualified model
        # name via the one resolver that already exists - never a second
        # provider table.
        external_provider = llm_config_service.resolve_provider_for_model(result.external_model)
    return {
        **result.model_dump(),
        "external_provider": external_provider,
        "local_model_supports_vision": ollama_catalog.supports_vision(result.local_model),
    }


@router.get("/workspaces/{workspace_slug}/llm-config", response_model=LlmConfigResponse)
def read_llm_config(workspace_slug: str):
    try:
        result = llm_config_service.read_for_workspace(workspace_slug)
    except llm_config_service.WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _with_vision_capability(result)


@router.put("/workspaces/{workspace_slug}/llm-config", response_model=LlmConfigResponse)
def update_llm_config(workspace_slug: str, body: LlmConfigUpdate):
    try:
        result = llm_config_service.update_for_workspace(
            workspace_slug,
            body.model_dump(),
            set(body.model_fields_set),
        )
    except llm_config_service.WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except llm_config_service.InvalidLlmConfigUpdate as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Makes this process's own next read instant instead of waiting on the
    # pipeline config cache's TTL/mtime check - other processes (the Celery
    # worker, a second FastAPI worker) still pick it up via that check, see
    # services/pipeline_config_cache.py.
    pipeline_config_cache.invalidate(workspace_slug)
    return _with_vision_capability(result)
