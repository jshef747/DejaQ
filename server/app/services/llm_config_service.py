from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.config import EXTERNAL_MODEL_NAME, LOCAL_LLM_MODEL_NAME, ROUTING_THRESHOLD
from app.db import credential_repo, llm_config_repo
from app.db.models.workspace import Workspace
from app.db.session import get_session


class WorkspaceNotFound(Exception):
    def __init__(self, workspace_slug: str) -> None:
        self.workspace_slug = workspace_slug
        super().__init__(f"Workspace '{workspace_slug}' not found.")


class InvalidLlmConfigUpdate(Exception):
    pass


class LlmConfigResult(BaseModel):
    external_model: str
    local_model: str
    routing_threshold: float
    overrides: dict[str, str | float]
    updated_at: datetime | None
    is_default: bool
    credentials_configured: list[str]


def _effective(row, credentials_configured: list[str] | None = None) -> LlmConfigResult:
    values = {
        "external_model": row.external_model if row and row.external_model is not None else EXTERNAL_MODEL_NAME,
        "local_model": row.local_model if row and row.local_model is not None else LOCAL_LLM_MODEL_NAME,
        "routing_threshold": (
            row.routing_threshold
            if row and row.routing_threshold is not None
            else ROUTING_THRESHOLD
        ),
    }
    overrides: dict[str, str | float] = {}
    if row:
        for field in ("external_model", "local_model", "routing_threshold"):
            stored = getattr(row, field)
            if stored is not None:
                overrides[field] = stored

    return LlmConfigResult(
        **values,
        overrides=overrides,
        updated_at=row.updated_at if row else None,
        is_default=not overrides,
        credentials_configured=credentials_configured or [],
    )


def _get_workspace(session, workspace_slug: str) -> Workspace:
    workspace = session.query(Workspace).filter_by(slug=workspace_slug).first()
    if workspace is None:
        raise WorkspaceNotFound(workspace_slug)
    return workspace


def read_for_workspace(workspace_slug: str) -> LlmConfigResult:
    with get_session() as session:
        workspace = _get_workspace(session, workspace_slug)
        row = llm_config_repo.get_for_workspace(session, workspace.id)
        credentials = [item.provider for item in credential_repo.list_credentials(session, workspace.id)]
        return _effective(row, credentials)


def update_for_workspace(
    workspace_slug: str,
    payload: dict[str, Any],
    fields_set: set[str],
) -> LlmConfigResult:
    if not fields_set:
        raise InvalidLlmConfigUpdate("At least one config field is required.")

    with get_session() as session:
        workspace = _get_workspace(session, workspace_slug)
        row = llm_config_repo.upsert_for_workspace(session, workspace.id, payload, fields_set)
        credentials = [item.provider for item in credential_repo.list_credentials(session, workspace.id)]
        return _effective(row, credentials)
