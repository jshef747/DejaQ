from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.config import (
    CACHE_DRAFTS_ENABLED,
    CACHE_DRAFTS_MAX_DELTA,
    CACHE_DRAFTS_MAX_DISTANCE,
    CACHE_TRUST_DISTANCE,
    CONTEXT_ADJUSTER_MODEL_NAME,
    DEFAULT_CLASSIFIER_CHOICE,
    DEFAULT_MAX_TOKENS,
    ENRICHER_MODEL_NAME,
    EXTERNAL_MODEL_NAME,
    GENERALIZER_MODEL_NAME,
    LEGACY_ROUTING_THRESHOLD,
    LOCAL_ATTACHMENT_MAX_TOKENS,
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
from app.services import model_catalog, ollama_catalog
from app.services.context_adjuster import (
    DEFAULT_ADJUST_SYSTEM_PROMPT,
    DEFAULT_GENERALIZE_SYSTEM_PROMPT,
)
from app.services.context_enricher import DEFAULT_SYSTEM_PROMPT as ENRICHER_DEFAULT_SYSTEM_PROMPT
from app.services.llm_providers.litellm_transport import _LITELLM_PROVIDER_KEYS, _litellm_key
from app.services.llm_router import DEFAULT_SYSTEM_PROMPT as LOCAL_DEFAULT_SYSTEM_PROMPT
from app.services.model_backends import MODEL_RUNTIME_SPECS
from app.services.model_catalog import STRUCTURED_CREDENTIAL_PROVIDERS
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

_CLASSIFIER_CHOICES = {"legacy", "labse"}

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

# Alternative-draft override fields - each mirrors a CACHE_DRAFTS_* global in
# app/config.py. Validated for the RELATIONSHIP between the two thresholds and
# against the trusted-zone ceiling (§ _validate_draft_overrides), for the same
# reason the token budgets are: each value can look reasonable on its own while
# the combination is incoherent.
_DRAFT_FIELDS = {
    "drafts_enabled",
    "drafts_max_distance",
    "drafts_max_delta",
}

# The two that participate in the relationship check. `drafts_enabled` is
# deliberately NOT here: it is a switch, not a threshold, and validating the
# pair on a bare on/off toggle would let a deployment whose CACHE_DRAFTS_*
# env defaults sit outside the bounds reject `{"drafts_enabled": true}` for a
# field the admin never sent and cannot see in that request.
_DRAFT_THRESHOLD_FIELDS = {
    "drafts_max_distance",
    "drafts_max_delta",
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
    # The provider recorded for external_model (validated against LiteLLM at
    # write time, see _validate_and_resolve_external_model below), or None
    # for a row written before this column existed / a workspace that
    # has never changed its external_model. The qualification migration
    # (f7a8b9c0d1e2) backfills every placeable row once; nothing at read time
    # guesses on a row's behalf any more.
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
    # "legacy" or "labse" - which classifier this workspace routes on.
    classifier_choice: str
    # The legacy classifier's own threshold, kept separate from
    # routing_threshold (LaBSE's) because the two classifiers score on
    # different scales - see app/config.py's LEGACY_ROUTING_THRESHOLD.
    legacy_routing_threshold: float
    default_max_tokens: int
    rewrite_max_tokens: int
    ollama_num_ctx: int
    # Ceiling on an attached file's extracted-text size (tokens) for local
    # answering - see LOCAL_ATTACHMENT_MAX_TOKENS in app/config.py. Not part
    # of the three-way generation-budget relationship above (it bounds
    # attachment size, not generation length), so it is not validated
    # against them.
    local_attachment_max_tokens: int
    drafts_enabled: bool
    drafts_max_distance: float
    drafts_max_delta: float
    # The shipped/global default for each of the resolved fields above, ALWAYS -
    # regardless of whether this workspace overrides it. The fields above are
    # the EFFECTIVE value (override-or-default), so once a workspace has an
    # override set, nothing else in this response still names what clearing
    # it restores; a client (the dashboard's "empty uses the default"
    # placeholder) needs the true default value, not the override, to render
    # that correctly. Hardcoding these client-side would drift from a
    # deployment that sets DEJAQ_DEFAULT_MAX_TOKENS etc.
    token_budget_defaults: dict[str, int]
    # Same contract as token_budget_defaults, for the two draft thresholds: the
    # effective fields above become the override once one is set, so nothing
    # else in this response still names what clearing it restores.
    draft_defaults: dict[str, float]
    overrides: dict[str, str | float | int | bool]
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
        "classifier_choice": (
            row.classifier_choice if row and row.classifier_choice is not None else DEFAULT_CLASSIFIER_CHOICE
        ),
        "legacy_routing_threshold": (
            row.legacy_routing_threshold
            if row and row.legacy_routing_threshold is not None
            else LEGACY_ROUTING_THRESHOLD
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
        "local_attachment_max_tokens": (
            row.local_attachment_max_tokens if row and row.local_attachment_max_tokens is not None
            else LOCAL_ATTACHMENT_MAX_TOKENS
        ),
        "drafts_enabled": (
            row.drafts_enabled if row and row.drafts_enabled is not None else CACHE_DRAFTS_ENABLED
        ),
        "drafts_max_distance": (
            row.drafts_max_distance if row and row.drafts_max_distance is not None
            else CACHE_DRAFTS_MAX_DISTANCE
        ),
        "drafts_max_delta": (
            row.drafts_max_delta if row and row.drafts_max_delta is not None
            else CACHE_DRAFTS_MAX_DELTA
        ),
    }
    overrides: dict[str, str | float | int | bool] = {}
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
            "classifier_choice",
            "legacy_routing_threshold",
            "default_max_tokens",
            "rewrite_max_tokens",
            "ollama_num_ctx",
            "local_attachment_max_tokens",
            "drafts_enabled",
            "drafts_max_distance",
            "drafts_max_delta",
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
            "local_attachment_max_tokens": LOCAL_ATTACHMENT_MAX_TOKENS,
        },
        draft_defaults={
            "drafts_max_distance": CACHE_DRAFTS_MAX_DISTANCE,
            "drafts_max_delta": CACHE_DRAFTS_MAX_DELTA,
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


def _validate_classifier_choice(payload: dict[str, Any], fields_set: set[str]) -> None:
    """Reject a classifier_choice that isn't one of the two supported classifiers.

    Null (reset-to-default) is always accepted - it restores
    config.DEFAULT_CLASSIFIER_CHOICE. Mirrors the schema-level Literal check
    in schemas/admin/llm_config.py so a direct update_for_workspace() call
    (as the test suite makes) gets the same guarantee.
    """
    if "classifier_choice" not in fields_set:
        return
    value = payload.get("classifier_choice")
    if value is not None and value not in _CLASSIFIER_CHOICES:
        raise InvalidLlmConfigUpdate(
            f"classifier_choice: '{value}' must be one of {sorted(_CLASSIFIER_CHOICES)} (or null for the default)."
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


# Inverse of litellm_transport's DejaQ->LiteLLM provider-key map: DejaQ's
# credential lookup (get_workspace_provider_key, still keyed on DejaQ's own
# provider names) needs the DejaQ key back from whatever LiteLLM's
# get_llm_provider() resolves. Migration stage A1's provider-key-namespace
# unification (plan section 2.11, "M7") deletes both maps together; it is
# not part of this stage.
_DEJAQ_PROVIDER_KEYS = {litellm_key: dejaq_key for dejaq_key, litellm_key in _LITELLM_PROVIDER_KEYS.items()}

# Frozen copy of the 38 model ids the deleted `provider_registry.PROVIDERS`
# used to carry for DejaQ's six live providers - the one part of that
# registry still load-bearing after A1 (plan section 2.11 / A1c). Exists
# only for `resolve_provider_for_model` below: a bare (unqualified) model
# name still needs an EXACT lookup, never a guess - LiteLLM's own bare-name
# resolution is provably wrong for several of these (verified in migration
# f7a8b9c0d1e2's docstring: every `gemini-*` id resolves to `vertex_ai`, not
# `gemini`, and Groq's `openai/gpt-oss-*` ids resolve to `openai`, not
# `groq`). Keys are the literal ids DejaQ has stored historically, including
# Groq's own ids that already carry a "/" (`openai/gpt-oss-120b`) - that is
# why lookup below cannot use "contains a slash" to tell a bare legacy id
# apart from a DejaQ-qualified one (`gemini/gemini-2.5-flash`).
_LEGACY_BARE_MODEL_PROVIDERS: dict[str, str] = {
    "gemini-3.6-flash": "google",
    "gemini-3.5-flash": "google",
    "gemini-3.5-flash-lite": "google",
    "gemini-3.1-flash-lite": "google",
    "gemini-2.5-pro": "google",
    "gemini-2.5-flash": "google",
    "gemini-2.5-flash-lite": "google",
    "gpt-5.6-sol": "openai",
    "gpt-5.6-terra": "openai",
    "gpt-5.6-luna": "openai",
    "gpt-4.1": "openai",
    "gpt-4.1-mini": "openai",
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
    "claude-fable-5": "anthropic",
    "claude-opus-5": "anthropic",
    "claude-sonnet-5": "anthropic",
    "claude-haiku-4-5-20251001": "anthropic",
    "claude-opus-4-8": "anthropic",
    "claude-opus-4-7": "anthropic",
    "claude-opus-4-6": "anthropic",
    "claude-sonnet-4-6": "anthropic",
    "claude-sonnet-4-5-20250929": "anthropic",
    "claude-opus-4-5-20251101": "anthropic",
    "grok-4.6": "xai",
    "grok-4.5": "xai",
    "grok-4.3": "xai",
    "grok-4.20-0309-reasoning": "xai",
    "grok-4.20-0309-non-reasoning": "xai",
    "grok-4.20-multi-agent-0309": "xai",
    "grok-build-0.1": "xai",
    "deepseek-v4-flash": "deepseek",
    "deepseek-v4-pro": "deepseek",
    "openai/gpt-oss-120b": "groq",
    "openai/gpt-oss-20b": "groq",
    "groq/compound": "groq",
    "groq/compound-mini": "groq",
    "qwen/qwen3.6-27b": "groq",
}


def resolve_provider_for_model(model: str) -> str | None:
    """DejaQ's own provider key for `model`, or None if it can't be placed.

    The exact legacy table is tried first (see its own comment for why "has
    a slash" cannot gate this), then LiteLLM's own qualified-name
    resolution - exact once a model actually carries its provider prefix.

    The one remaining caller of the deleted `provider_registry`'s registry
    fallback (`openai_compat.py`, `escalation.py`, `test_provider.py`): a
    config with no recorded `external_provider`, chiefly the server-wide
    `DEJAQ_EXTERNAL_MODEL` env default, which has no database row to record
    one in. See AGENTS.md "Provider resolution needs a registry fallback".
    """
    dejaq_provider = _LEGACY_BARE_MODEL_PROVIDERS.get(model)
    if dejaq_provider is not None:
        return dejaq_provider
    try:
        litellm_provider = model_catalog.resolve_provider(model)
    except ValueError:
        return None
    return _DEJAQ_PROVIDER_KEYS.get(litellm_provider, litellm_provider)


def _validate_and_resolve_external_model(payload: dict[str, Any], fields_set: set[str]) -> dict[str, Any]:
    """Accept every model LiteLLM can address; reject only what it cannot.

    Four assertions, in this order (plan `dejaq-litellm-migration-plan-v2/
    report.md` section 2.11):

    1. `litellm.get_llm_provider(model)` must not raise, and the returned
       provider must be a real LiteLLM provider. This is what rejects a bare
       model name like 'grok-4.6'.
    2. The resolved provider and the DejaQ credential-lookup key this
       function is about to store for it agree (round-trip through the same
       map `litellm_transport` uses to build the wire model string).
    3. The provider is not in STRUCTURED_CREDENTIAL_PROVIDERS (Bedrock/Azure
       and their sibling keys) - workspace_provider_credentials stores one
       opaque string per provider, and SigV4 / endpoint+api-version+deployment
       don't fit. This is what stops a hand-typed 'bedrock/...' model from
       walking around the catalog filter (app/services/model_catalog.py).
    4. Nothing else - specifically NOT "is this model in litellm.model_cost".
       A model LiteLLM has never heard of (e.g. groq/compound) must stay
       callable; refusing unknown models breaks the product the day a vendor
       ships one.

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

    try:
        litellm_provider = model_catalog.resolve_provider(model)
    except ValueError as exc:
        hint_provider = resolve_provider_for_model(model)
        example = f"{_litellm_key(hint_provider)}/{model}" if hint_provider else f"<provider>/{model}"
        raise InvalidLlmConfigUpdate(
            f"external_model: '{model}' is not addressable by LiteLLM - qualify it "
            f"with its provider, e.g. '{example}' (see litellm.provider_list)."
        ) from exc

    external_provider = _DEJAQ_PROVIDER_KEYS.get(litellm_provider, litellm_provider)
    if _litellm_key(external_provider) != litellm_provider:
        raise InvalidLlmConfigUpdate(
            f"external_model: '{model}' - provider '{litellm_provider}' does not "
            "round-trip through DejaQ's provider-key map."
        )

    if litellm_provider in STRUCTURED_CREDENTIAL_PROVIDERS:
        raise InvalidLlmConfigUpdate(
            f"external_model: '{model}' - provider '{litellm_provider}' needs a "
            "structured credential (more than one field) that "
            "workspace_provider_credentials cannot store yet "
            "(app/services/model_catalog.py:STRUCTURED_CREDENTIAL_PROVIDERS)."
        )

    return {"external_provider": external_provider}


def _effective_draft_value(
    field: str,
    payload: dict[str, Any],
    fields_set: set[str],
    row,
    global_default: float,
) -> float:
    """The value `field` would have AFTER this update lands - same contract as
    _effective_token_value, and for the same reason: the relationship between
    the two draft thresholds has to be judged against the resulting pair, not
    against whichever one this particular PUT happens to carry."""
    if field in fields_set:
        value = payload.get(field)
        return value if value is not None else global_default
    stored = getattr(row, field, None) if row is not None else None
    return stored if stored is not None else global_default


def _validate_draft_overrides(payload: dict[str, Any], fields_set: set[str], row) -> None:
    """Reject an alternative-draft threshold combination that cannot mean anything.

    - Both thresholds must be positive. A zero or negative distance window
      offers nothing; a zero delta would only fire on an exact numerical tie.
    - `drafts_max_delta` must not exceed `drafts_max_distance`. A tie tolerance
      wider than the window it operates inside is incoherent - every pair
      inside the window would count as tied, which is not a tie-breaker, it is
      an always-on second answer.
    - `drafts_max_distance` is capped at CACHE_TRUST_DISTANCE, the trusted-zone
      ceiling. BOTH drafts are validated on merit: the served answer like any
      other hit, and the alternate by its own validate() call on the tie path
      (openai_compat.py, `validate_alt`), added precisely so this cap could be
      the trusted ceiling rather than VALIDATOR_SKIP_DISTANCE. The earlier,
      much tighter cap existed only because the alternate was shown unchecked -
      which is what made numbered-item siblings ("solve part a" / "part b",
      measured 0.0898) dangerous inside the trusted zone. The validator is what
      separates those from a real paraphrase, and it now runs on the alternate,
      so the trusted ceiling is the right bound. Above it the embedding is no
      longer trusted for the SERVED answer either, which is why the cap stops
      there and not higher.

    Only reachable when this update actually touches one of the draft fields.
    """
    max_distance = _effective_draft_value(
        "drafts_max_distance", payload, fields_set, row, CACHE_DRAFTS_MAX_DISTANCE
    )
    max_delta = _effective_draft_value(
        "drafts_max_delta", payload, fields_set, row, CACHE_DRAFTS_MAX_DELTA
    )

    if max_distance <= 0:
        raise InvalidLlmConfigUpdate(
            f"drafts_max_distance: {max_distance} must be greater than 0 - it is a "
            "cosine distance ceiling, and a window of zero can never contain a candidate."
        )
    if max_delta <= 0:
        raise InvalidLlmConfigUpdate(
            f"drafts_max_delta: {max_delta} must be greater than 0 - a delta of zero "
            "would only fire on an exact numerical tie, which effectively disables the "
            "feature. Clear drafts_enabled to turn it off instead."
        )
    if max_delta > max_distance:
        raise InvalidLlmConfigUpdate(
            f"drafts_max_delta: {max_delta} cannot exceed the quality window "
            f"({max_distance}, drafts_max_distance) - a tie tolerance wider than the "
            "window it operates inside makes every candidate in that window count as "
            "tied, which is an always-on second answer rather than a tie-breaker."
        )
    if max_distance > CACHE_TRUST_DISTANCE:
        raise InvalidLlmConfigUpdate(
            f"drafts_max_distance: {max_distance} exceeds the ceiling of "
            f"{CACHE_TRUST_DISTANCE} (CACHE_TRUST_DISTANCE). Both drafts are "
            "validated - the served answer like any other hit, the alternate by its "
            "own validator call on the tie path - so the bound is the trusted zone "
            "itself. Past it the embedding is no longer trusted for the SERVED "
            "answer either, and a window that reaches into the validator-guarded "
            "band would offer a candidate the pipeline does not serve unguarded."
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
    _validate_classifier_choice(payload, fields_set)
    derived = _validate_and_resolve_external_model(payload, fields_set)
    if derived:
        payload = {**payload, **derived}
        fields_set = fields_set | set(derived)

    with get_session() as session:
        workspace = _get_workspace(session, workspace_slug)
        if fields_set & (_TOKEN_BUDGET_FIELDS | _DRAFT_THRESHOLD_FIELDS):
            existing_row = llm_config_repo.get_for_workspace(session, workspace.id)
            if fields_set & _TOKEN_BUDGET_FIELDS:
                _validate_token_budget_overrides(payload, fields_set, existing_row)
            if fields_set & _DRAFT_THRESHOLD_FIELDS:
                _validate_draft_overrides(payload, fields_set, existing_row)
        row = llm_config_repo.upsert_for_workspace(session, workspace.id, payload, fields_set)
        credentials = [item.provider for item in credential_repo.list_credentials(session, workspace.id)]
        return _effective(row, credentials)
