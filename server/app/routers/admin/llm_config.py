from fastapi import APIRouter, HTTPException

from app.schemas.admin.llm_config import LlmConfigResponse, LlmConfigUpdate
from app.services import llm_config_service

router = APIRouter()


@router.get("/workspaces/{workspace_slug}/llm-config", response_model=LlmConfigResponse)
def read_llm_config(workspace_slug: str):
    try:
        return llm_config_service.read_for_workspace(workspace_slug)
    except llm_config_service.WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/workspaces/{workspace_slug}/llm-config", response_model=LlmConfigResponse)
def update_llm_config(workspace_slug: str, body: LlmConfigUpdate):
    try:
        return llm_config_service.update_for_workspace(
            workspace_slug,
            body.model_dump(),
            set(body.model_fields_set),
        )
    except llm_config_service.WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except llm_config_service.InvalidLlmConfigUpdate as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
