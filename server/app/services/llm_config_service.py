from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.config import EXTERNAL_MODEL_NAME, LOCAL_LLM_MODEL_NAME, ROUTING_THRESHOLD
from app.db import llm_config_repo
from app.db.models.org import Organization
from app.db.session import get_session


class OrgNotFound(Exception):
    def __init__(self, org_slug: str) -> None:
        self.org_slug = org_slug
        super().__init__(f"Organization '{org_slug}' not found.")


class InvalidLlmConfigUpdate(Exception):
    pass


class LlmConfigResult(BaseModel):
    external_model: str
    local_model: str
    routing_threshold: float
    overrides: dict[str, str | float]
    updated_at: datetime | None
    is_default: bool


def _effective(row) -> LlmConfigResult:
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
    )


def _get_org(session, org_slug: str) -> Organization:
    org = session.query(Organization).filter_by(slug=org_slug).first()
    if org is None:
        raise OrgNotFound(org_slug)
    return org


def read_for_org(org_slug: str) -> LlmConfigResult:
    with get_session() as session:
        org = _get_org(session, org_slug)
        row = llm_config_repo.get_for_org(session, org.id)
        return _effective(row)


def update_for_org(
    org_slug: str,
    payload: dict[str, Any],
    fields_set: set[str],
) -> LlmConfigResult:
    if not fields_set:
        raise InvalidLlmConfigUpdate("At least one config field is required.")

    with get_session() as session:
        org = _get_org(session, org_slug)
        row = llm_config_repo.upsert_for_org(session, org.id, payload, fields_set)
        return _effective(row)
