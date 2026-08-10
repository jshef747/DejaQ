from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.config import (
    CONTEXT_ADJUSTER_MODEL_NAME,
    ENRICHER_MODEL_NAME,
    EXTERNAL_MODEL_NAME,
    GENERALIZER_MODEL_NAME,
    LOCAL_LLM_MODEL_NAME,
    NORMALIZER_MODEL_NAME,
    ROUTING_THRESHOLD,
    VALIDATOR_MODEL_NAME,
)
from app.db import credential_repo, llm_config_repo
from app.db.models.workspace import Workspace
from app.db.session import get_session
from app.services import ollama_catalog
from app.services.context_adjuster import (
    DEFAULT_ADJUST_SYSTEM_PROMPT,
    DEFAULT_GENERALIZE_SYSTEM_PROMPT,
)
from app.services.context_enricher import DEFAULT_SYSTEM_PROMPT as ENRICHER_DEFAULT_SYSTEM_PROMPT
from app.services.llm_router import DEFAULT_SYSTEM_PROMPT as LOCAL_DEFAULT_SYSTEM_PROMPT
from app.services.model_backends import MODEL_RUNTIME_SPECS
from app.services.normalizer import DEFAULT_SYSTEM_PROMPT as NORMALIZER_DEFAULT_SYSTEM_PROMPT
from app.services.validator import (
    DEFAULT_IMAGE_SYSTEM_PROMPT as VALIDATOR_DEFAULT_IMAGE_SYSTEM_PROMPT,
    DEFAULT_SYSTEM_PROMPT as VALIDATOR_DEFAULT_SYSTEM_PROMPT,
)

# Fields whose value must name a model actually installed on the configured
# Ollama host (captain's decision: any installed tag is selectable, not just
# ones registered in MODEL_RUNTIME_SPECS - see model_backends.py). Distinct
# from external_model, which names a provider model string, not an Ollama tag.
_OLLAMA_ROLE_FIELDS = {
    "local_model",
    "generalizer_model",
    "adjuster_model",
    "enricher_model",
    "normalizer_model",
    "validator_model",
}

# Prompt override fields - validated for non-empty content only (§
# _validate_prompt_overrides), never against Ollama. Also the source of
# truth PROMPT_FIELDS in schemas/admin/llm_config.py mirrors for its own
# Pydantic-level check.
_PROMPT_FIELDS = {
    "enricher_system_prompt",
    "normalizer_system_prompt",
    "validator_system_prompt",
    "validator_image_system_prompt",
    "adjuster_system_prompt",
    "generalizer_system_prompt",
    "local_model_system_prompt",
}


class WorkspaceNotFound(Exception):
    def __init__(self, workspace_slug: str) -> None:
        self.workspace_slug = workspace_slug
        super().__init__(f"Workspace '{workspace_slug}' not found.")


class InvalidLlmConfigUpdate(Exception):
    pass


class LlmConfigResult(BaseModel):
    external_model: str
    local_model: str
    generalizer_model: str
    adjuster_model: str
    enricher_model: str
    normalizer_model: str
    validator_model: str
    enricher_system_prompt: str
    normalizer_system_prompt: str
    validator_system_prompt: str
    validator_image_system_prompt: str
    adjuster_system_prompt: str
    generalizer_system_prompt: str
    local_model_system_prompt: str
    routing_threshold: float
    overrides: dict[str, str | float]
    updated_at: datetime | None
    is_default: bool
    credentials_configured: list[str]


def _shipped_default_ollama_tag(logical_model_name: str) -> str:
    """The real Ollama tag a shipped-default *_model config value maps to.

    Config defaults (LOCAL_LLM_MODEL_NAME etc.) are DejaQ's internal logical
    names ("gemma_local"), never something Ollama itself would recognise -
    only a workspace override (validated at write time) is a raw tag. The
    dashboard picker's option list is sourced live from Ollama, so surfacing
    the untranslated logical name here would make every untouched default
    look like a missing model ("gemma_local (not installed)") even though it
    resolves correctly. Falls back to the input unchanged if it's somehow
    not in the map, matching OllamaBackend._resolve_model's own passthrough.
    """
    spec = MODEL_RUNTIME_SPECS.get(logical_model_name)
    return spec.ollama_model if spec else logical_model_name


def _effective(row, credentials_configured: list[str] | None = None) -> LlmConfigResult:
    values = {
        "external_model": row.external_model if row and row.external_model is not None else EXTERNAL_MODEL_NAME,
        "local_model": (
            row.local_model if row and row.local_model is not None
            else _shipped_default_ollama_tag(LOCAL_LLM_MODEL_NAME)
        ),
        "generalizer_model": (
            row.generalizer_model if row and row.generalizer_model is not None
            else _shipped_default_ollama_tag(GENERALIZER_MODEL_NAME)
        ),
        "adjuster_model": (
            row.adjuster_model if row and row.adjuster_model is not None
            else _shipped_default_ollama_tag(CONTEXT_ADJUSTER_MODEL_NAME)
        ),
        "enricher_model": (
            row.enricher_model if row and row.enricher_model is not None
            else _shipped_default_ollama_tag(ENRICHER_MODEL_NAME)
        ),
        "normalizer_model": (
            row.normalizer_model if row and row.normalizer_model is not None
            else _shipped_default_ollama_tag(NORMALIZER_MODEL_NAME)
        ),
        "validator_model": (
            row.validator_model if row and row.validator_model is not None
            else _shipped_default_ollama_tag(VALIDATOR_MODEL_NAME)
        ),
        "enricher_system_prompt": (
            row.enricher_system_prompt if row and row.enricher_system_prompt is not None
            else ENRICHER_DEFAULT_SYSTEM_PROMPT
        ),
        "normalizer_system_prompt": (
            row.normalizer_system_prompt if row and row.normalizer_system_prompt is not None
            else NORMALIZER_DEFAULT_SYSTEM_PROMPT
        ),
        "validator_system_prompt": (
            row.validator_system_prompt if row and row.validator_system_prompt is not None
            else VALIDATOR_DEFAULT_SYSTEM_PROMPT
        ),
        "validator_image_system_prompt": (
            row.validator_image_system_prompt if row and row.validator_image_system_prompt is not None
            else VALIDATOR_DEFAULT_IMAGE_SYSTEM_PROMPT
        ),
        "adjuster_system_prompt": (
            row.adjuster_system_prompt if row and row.adjuster_system_prompt is not None
            else DEFAULT_ADJUST_SYSTEM_PROMPT
        ),
        "generalizer_system_prompt": (
            row.generalizer_system_prompt if row and row.generalizer_system_prompt is not None
            else DEFAULT_GENERALIZE_SYSTEM_PROMPT
        ),
        "local_model_system_prompt": (
            row.local_model_system_prompt if row and row.local_model_system_prompt is not None
            else LOCAL_DEFAULT_SYSTEM_PROMPT
        ),
        "routing_threshold": (
            row.routing_threshold
            if row and row.routing_threshold is not None
            else ROUTING_THRESHOLD
        ),
    }
    overrides: dict[str, str | float] = {}
    if row:
        for field in (
            "external_model",
            "local_model",
            "generalizer_model",
            "adjuster_model",
            "enricher_model",
            "normalizer_model",
            "validator_model",
            "enricher_system_prompt",
            "normalizer_system_prompt",
            "validator_system_prompt",
            "validator_image_system_prompt",
            "adjuster_system_prompt",
            "generalizer_system_prompt",
            "local_model_system_prompt",
            "routing_threshold",
        ):
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


def _validate_ollama_overrides(payload: dict[str, Any], fields_set: set[str]) -> None:
    """Reject a *_model override naming a tag Ollama doesn't currently report.

    Null values (reset-to-default) skip validation entirely - Ollama doesn't
    need to be reachable to clear an override. A forced refresh is used
    rather than the discovery endpoint's own TTL cache: this is a write, not
    a page render, and it must judge against ground truth, not a list that
    could be up to OLLAMA_CATALOG_CACHE_TTL_SECONDS stale.
    """
    to_check = {f: payload.get(f) for f in fields_set & _OLLAMA_ROLE_FIELDS if payload.get(f) is not None}
    if not to_check:
        return
    try:
        available = ollama_catalog.list_available_models(force_refresh=True)
    except ollama_catalog.OllamaUnreachableError as exc:
        raise InvalidLlmConfigUpdate(
            f"Cannot validate model selection - {exc}"
        ) from exc
    for field, value in to_check.items():
        if value not in available:
            raise InvalidLlmConfigUpdate(
                f"{field}: '{value}' is not an Ollama model installed on the configured host."
            )


def _validate_prompt_overrides(payload: dict[str, Any], fields_set: set[str]) -> None:
    """Reject a blank (empty or whitespace-only) prompt override.

    Null (reset-to-default) is the only way to clear a prompt override - a
    blank string would ship a role with no system prompt at all, which is
    very likely to break a role with a structural output format (e.g. the
    validator's one-word VALID/INVALID verdict). Mirrors the schema-level
    check in schemas/admin/llm_config.py so a direct update_for_workspace()
    call (as the test suite makes) gets the same guarantee a request through
    the Pydantic-validated router does.
    """
    for field in fields_set & _PROMPT_FIELDS:
        value = payload.get(field)
        if isinstance(value, str) and value.strip() == "":
            raise InvalidLlmConfigUpdate(
                f"{field}: prompt cannot be empty - reset to null to use the shipped default."
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

    _validate_ollama_overrides(payload, fields_set)
    _validate_prompt_overrides(payload, fields_set)

    with get_session() as session:
        workspace = _get_workspace(session, workspace_slug)
        row = llm_config_repo.upsert_for_workspace(session, workspace.id, payload, fields_set)
        credentials = [item.provider for item in credential_repo.list_credentials(session, workspace.id)]
        return _effective(row, credentials)
