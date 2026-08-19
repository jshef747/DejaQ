from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.config import (
    CONTEXT_ADJUSTER_MODEL_NAME,
    DEFAULT_MAX_TOKENS,
    ENRICHER_MODEL_NAME,
    EXTERNAL_MODEL_NAME,
    GENERALIZER_MODEL_NAME,
    LOCAL_LLM_MODEL_NAME,
    NORMALIZER_MODEL_NAME,
    OLLAMA_NUM_CTX,
    REWRITE_MAX_TOKENS,
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
from app.services.provider_registry import provider_for_registered_model
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

# Token budget override fields - each mirrors a global default in
# app/config.py (DEFAULT_MAX_TOKENS, REWRITE_MAX_TOKENS, OLLAMA_NUM_CTX).
# Validated for the RELATIONSHIP between all three (§
# _validate_token_budget_overrides), not just per-field bounds - see that
# function's docstring for why a per-field check alone is not sufficient.
_TOKEN_BUDGET_FIELDS = {
    "default_max_tokens",
    "rewrite_max_tokens",
    "ollama_num_ctx",
}

# 1024 is not a guess - it's the exact value config.py records as having
# measurably truncated ordinary answers mid-sentence before DEFAULT_MAX_TOKENS
# was raised to 4096 (see the comment there). Refuse it and anything at or
# below it outright rather than accept a value already known to fail.
_MIN_ANSWER_MAX_TOKENS = 1024

# The shipped defaults already establish these ratios (8192 / 4096 = 2x,
# 32768 / 8192 = 4x); enforced here as floors so a custom combination cannot
# recreate the 2026-08-16 incident (a 300-token generation cap silently
# stopped the cache from filling - see the PR description for the measured
# numbers). Using the smaller of the two shipped ratios (2x) as the floor for
# both relationships keeps real headroom on each side without forcing every
# workspace to reproduce the shipped numbers exactly.
_MIN_REWRITE_OVER_ANSWER_RATIO = 2.0
_MIN_CTX_OVER_REWRITE_RATIO = 2.0


class WorkspaceNotFound(Exception):
    def __init__(self, workspace_slug: str) -> None:
        self.workspace_slug = workspace_slug
        super().__init__(f"Workspace '{workspace_slug}' not found.")


class InvalidLlmConfigUpdate(Exception):
    pass


class LlmConfigResult(BaseModel):
    # None only when the workspace has no override AND no DEJAQ_EXTERNAL_MODEL
    # env default is set - openai_compat.py turns that into a 422 before any
    # external call is attempted.
    external_model: str | None
    # The provider recorded for external_model (app.services.provider_registry),
    # or None for a row written before this column existed / a workspace that
    # has never changed its external_model - resolve_provider() in
    # provider_inference.py is what falls back to the name-prefix guess for
    # that case; nothing here guesses on its behalf.
    external_provider: str | None
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
    default_max_tokens: int
    rewrite_max_tokens: int
    ollama_num_ctx: int
    # The shipped/global default for each of the three fields above, ALWAYS -
    # regardless of whether this workspace overrides it. The three fields
    # above are the EFFECTIVE value (override-or-default), so once a
    # workspace has an override set, nothing else in this response still
    # names what clearing it restores; a client (the dashboard's "empty uses
    # the default" placeholder) needs the true default value, not the
    # override, to render that correctly. Hardcoding these client-side would
    # drift from a deployment that sets DEJAQ_DEFAULT_MAX_TOKENS etc.
    token_budget_defaults: dict[str, int]
    overrides: dict[str, str | float | int]
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
        "external_provider": row.external_provider if row else None,
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
        "default_max_tokens": (
            row.default_max_tokens if row and row.default_max_tokens is not None else DEFAULT_MAX_TOKENS
        ),
        "rewrite_max_tokens": (
            row.rewrite_max_tokens if row and row.rewrite_max_tokens is not None else REWRITE_MAX_TOKENS
        ),
        "ollama_num_ctx": (
            row.ollama_num_ctx if row and row.ollama_num_ctx is not None else OLLAMA_NUM_CTX
        ),
    }
    overrides: dict[str, str | float | int] = {}
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
            "default_max_tokens",
            "rewrite_max_tokens",
            "ollama_num_ctx",
        ):
            stored = getattr(row, field)
            if stored is not None:
                overrides[field] = stored

    return LlmConfigResult(
        **values,
        token_budget_defaults={
            "default_max_tokens": DEFAULT_MAX_TOKENS,
            "rewrite_max_tokens": REWRITE_MAX_TOKENS,
            "ollama_num_ctx": OLLAMA_NUM_CTX,
        },
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


def _effective_token_value(
    field: str,
    payload: dict[str, Any],
    fields_set: set[str],
    row,
    global_default: int,
) -> int:
    """The value `field` would have AFTER this update lands, whether or not
    this call actually touches it - a relationship check must judge the
    resulting combination of all three budgets, not just whichever one or two
    fields this particular request happens to change."""
    if field in fields_set:
        value = payload.get(field)
        return value if value is not None else global_default
    stored = getattr(row, field, None) if row is not None else None
    return stored if stored is not None else global_default


def _validate_token_budget_overrides(
    payload: dict[str, Any], fields_set: set[str], row
) -> None:
    """Reject a token-budget combination that would (re)create the failure
    measured on 2026-08-16: a generation cap so low that ordinary answers
    truncate, which the store guard then correctly refuses to cache - so the
    cache silently stops filling with no error anywhere. Per-field bounds
    (Pydantic's `gt=` on LlmConfigUpdate) catch an obviously-broken single
    value; they cannot catch a combination where each field looks reasonable
    alone but the RELATIONSHIP between them still truncates something:

    - the rewrite budget must be comfortably above the answer budget, because
      generalize()/adjust() are handed the whole raw answer and told to keep
      every fact - REWRITE_MAX_TOKENS ships at 2x DEFAULT_MAX_TOKENS for
      exactly this headroom (see app/config.py and context_adjuster.py);
    - the context window must be comfortably above the rewrite budget, because
      num_ctx bounds the PROMPT as well as the generation, and that prompt
      carries the whole answer being rewritten on top of the rewrite's own
      output budget - OLLAMA_NUM_CTX ships at 4x REWRITE_MAX_TOKENS;
    - the answer budget itself must clear the value config.py records as
      having measurably truncated ordinary answers mid-sentence;
    - the context window has a ceiling at OLLAMA_NUM_CTX itself: one window is
      sent to every Ollama-backed role sharing it, so the ceiling has to be
      the SMALLER of the models sharing it, not the larger - enricher and
      adjuster run qwen2.5:1.5b, whose own maximum context length is exactly
      what OLLAMA_NUM_CTX is set to (see its comment in app/config.py), while
      normalizer and validator run the much larger gemma4:e2b. Above the
      ceiling the two qwen roles cannot honour the window at all - not merely
      a bigger KV cache allocation on the shared Ollama host. The other two
      fields need no ceiling of their own: the relationship rules above
      already bound them transitively (rewrite <= ctx/2, answer <= rewrite/2).
      Accepted limitation: this assumes the shipped qwen2.5:1.5b assignment
      for the enricher/adjuster roles - a workspace that also overrides those
      roles to a model with more headroom is still capped here, since this
      reads the global constant rather than looking up per-workspace model
      overrides. A deployment that moves those roles to a larger-context model
      system-wide raises the ceiling itself via DEJAQ_OLLAMA_NUM_CTX.

    Only reachable when this update actually touches one of the three fields
    (see the `fields_set` guard at the call site) - an update to an unrelated
    field (a model name, a prompt) never re-validates budgets it isn't
    changing.
    """
    answer_budget = _effective_token_value(
        "default_max_tokens", payload, fields_set, row, DEFAULT_MAX_TOKENS
    )
    rewrite_budget = _effective_token_value(
        "rewrite_max_tokens", payload, fields_set, row, REWRITE_MAX_TOKENS
    )
    ctx_window = _effective_token_value(
        "ollama_num_ctx", payload, fields_set, row, OLLAMA_NUM_CTX
    )

    if answer_budget <= _MIN_ANSWER_MAX_TOKENS:
        raise InvalidLlmConfigUpdate(
            f"default_max_tokens: {answer_budget} is too low - {_MIN_ANSWER_MAX_TOKENS} tokens "
            "is the exact cap measured to truncate ordinary answers mid-sentence "
            "(see DEFAULT_MAX_TOKENS in app/config.py). Must be greater than "
            f"{_MIN_ANSWER_MAX_TOKENS}."
        )
    if rewrite_budget < _MIN_REWRITE_OVER_ANSWER_RATIO * answer_budget:
        raise InvalidLlmConfigUpdate(
            f"rewrite_max_tokens: {rewrite_budget} must be at least "
            f"{_MIN_REWRITE_OVER_ANSWER_RATIO:g}x the answer generation budget "
            f"({answer_budget}, default_max_tokens) - the rewrite prompt carries the "
            "whole raw answer and must keep every fact, so a rewrite budget too "
            "close to the answer budget risks truncating the STORED copy, which "
            "never self-heals."
        )
    if ctx_window < _MIN_CTX_OVER_REWRITE_RATIO * rewrite_budget:
        raise InvalidLlmConfigUpdate(
            f"ollama_num_ctx: {ctx_window} must be at least "
            f"{_MIN_CTX_OVER_REWRITE_RATIO:g}x the rewrite budget ({rewrite_budget}, "
            "rewrite_max_tokens) - the context window bounds the prompt as well as "
            "the generation, and it has to hold the rewrite's own output on top of "
            "the prompt carrying the answer being rewritten."
        )
    if ctx_window > OLLAMA_NUM_CTX:
        raise InvalidLlmConfigUpdate(
            f"ollama_num_ctx: {ctx_window} exceeds the ceiling of {OLLAMA_NUM_CTX} - "
            "one window is sent to every Ollama-backed role sharing it, so the "
            "ceiling is the SMALLER of the models sharing it, not the larger: "
            "enricher and adjuster run qwen2.5:1.5b, whose own maximum context "
            "length is exactly this value (see the OLLAMA_NUM_CTX comment in "
            "app/config.py). Above it those two roles cannot honour the window "
            "at all, not just oversize a KV cache on the shared Ollama host."
        )


def _validate_and_resolve_external_model(payload: dict[str, Any], fields_set: set[str]) -> dict[str, Any]:
    """Reject an external_model the registry doesn't know, and return the
    external_provider to persist alongside it.

    Only reachable when this update actually touches external_model, same
    guard style as _validate_ollama_overrides/_validate_prompt_overrides. A
    null value (reset-to-default) clears external_provider too rather than
    validating it - EXTERNAL_MODEL_NAME is a shipped constant, not admin
    input, so there is nothing here to reject.
    """
    if "external_model" not in fields_set:
        return {}
    model = payload.get("external_model")
    if model is None:
        return {"external_provider": None}
    provider = provider_for_registered_model(model)
    if provider is None:
        raise InvalidLlmConfigUpdate(
            f"external_model: '{model}' is not a known model - no provider in "
            "the registry offers it (app/services/provider_registry.py)."
        )
    return {"external_provider": provider}


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
    derived = _validate_and_resolve_external_model(payload, fields_set)
    if derived:
        payload = {**payload, **derived}
        fields_set = fields_set | set(derived)

    with get_session() as session:
        workspace = _get_workspace(session, workspace_slug)
        if fields_set & _TOKEN_BUDGET_FIELDS:
            existing_row = llm_config_repo.get_for_workspace(session, workspace.id)
            _validate_token_budget_overrides(payload, fields_set, existing_row)
        row = llm_config_repo.upsert_for_workspace(session, workspace.id, payload, fields_set)
        credentials = [item.provider for item in credential_repo.list_credentials(session, workspace.id)]
        return _effective(row, credentials)
