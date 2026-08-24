import pytest

from app.db import workspace_repo
from app.db.session import get_session


def _create_workspace(name: str = "Acme") -> None:
    with get_session() as session:
        workspace_repo.create_workspace(session, name)


def test_llm_config_read_returns_defaults_when_no_row(isolated_org_db):
    from app.config import EXTERNAL_MODEL_NAME, LOCAL_LLM_MODEL_NAME, ROUTING_THRESHOLD
    from app.services.llm_config_service import read_for_workspace
    from app.services.model_backends import MODEL_RUNTIME_SPECS

    _create_workspace()

    result = read_for_workspace("acme")

    assert result.external_model == EXTERNAL_MODEL_NAME
    # The resolved real Ollama tag, not the internal logical name
    # (LOCAL_LLM_MODEL_NAME) - the dashboard picker sources its options live
    # from Ollama, so surfacing the untranslated logical name would make
    # every untouched default look like a missing model.
    assert result.local_model == MODEL_RUNTIME_SPECS[LOCAL_LLM_MODEL_NAME].ollama_model
    assert result.routing_threshold == ROUTING_THRESHOLD
    assert result.overrides == {}
    assert result.updated_at is None
    assert result.is_default is True


def test_llm_config_update_preserves_omitted_fields_and_clears_nulls(isolated_org_db, monkeypatch):
    from app.config import EXTERNAL_MODEL_NAME
    from app.services import llm_config_service
    from app.services.llm_config_service import read_for_workspace, update_for_workspace

    monkeypatch.setattr(
        llm_config_service.ollama_catalog, "list_available_models", lambda force_refresh=False: ["gemma-4-e4b"]
    )
    _create_workspace()

    first = update_for_workspace(
        "acme",
        {"external_model": "gemini/gemini-2.5-pro", "local_model": "gemma-4-e4b"},
        {"external_model", "local_model"},
    )
    assert first.external_model == "gemini/gemini-2.5-pro"
    assert first.local_model == "gemma-4-e4b"
    assert first.overrides == {
        "external_model": "gemini/gemini-2.5-pro",
        "local_model": "gemma-4-e4b",
    }

    second = update_for_workspace(
        "acme",
        {"external_model": None},
        {"external_model"},
    )

    assert second.external_model == EXTERNAL_MODEL_NAME
    assert second.local_model == "gemma-4-e4b"
    assert second.overrides == {"local_model": "gemma-4-e4b"}

    stored = read_for_workspace("acme")
    assert stored.external_model == EXTERNAL_MODEL_NAME
    assert stored.local_model == "gemma-4-e4b"
    assert stored.is_default is False


def test_llm_config_empty_update_is_rejected(isolated_org_db):
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate):
        update_for_workspace("acme", {}, set())


def test_llm_config_unknown_workspace_raises(isolated_org_db):
    from app.services.llm_config_service import WorkspaceNotFound, read_for_workspace

    with pytest.raises(WorkspaceNotFound):
        read_for_workspace("missing")


def test_llm_config_read_defaults_cover_generalizer_and_adjuster(isolated_org_db):
    from app.config import CONTEXT_ADJUSTER_MODEL_NAME, GENERALIZER_MODEL_NAME
    from app.services.llm_config_service import read_for_workspace
    from app.services.model_backends import MODEL_RUNTIME_SPECS

    _create_workspace()

    result = read_for_workspace("acme")

    assert result.generalizer_model == MODEL_RUNTIME_SPECS[GENERALIZER_MODEL_NAME].ollama_model
    assert result.adjuster_model == MODEL_RUNTIME_SPECS[CONTEXT_ADJUSTER_MODEL_NAME].ollama_model
    assert "generalizer_model" not in result.overrides
    assert "adjuster_model" not in result.overrides


def test_llm_config_read_defaults_cover_enricher_normalizer_validator(isolated_org_db):
    from app.config import ENRICHER_MODEL_NAME, NORMALIZER_MODEL_NAME, VALIDATOR_MODEL_NAME
    from app.services.llm_config_service import read_for_workspace
    from app.services.model_backends import MODEL_RUNTIME_SPECS

    _create_workspace()

    result = read_for_workspace("acme")

    assert result.enricher_model == MODEL_RUNTIME_SPECS[ENRICHER_MODEL_NAME].ollama_model
    assert result.normalizer_model == MODEL_RUNTIME_SPECS[NORMALIZER_MODEL_NAME].ollama_model
    assert result.validator_model == MODEL_RUNTIME_SPECS[VALIDATOR_MODEL_NAME].ollama_model
    assert "enricher_model" not in result.overrides
    assert "normalizer_model" not in result.overrides
    assert "validator_model" not in result.overrides


# ── Write-time validation against the live Ollama catalog ──


def test_llm_config_update_rejects_a_model_not_in_the_ollama_catalog(isolated_org_db, monkeypatch):
    from app.services import llm_config_service
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    monkeypatch.setattr(
        llm_config_service.ollama_catalog, "list_available_models", lambda force_refresh=False: ["qwen2.5:1.5b"]
    )
    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate) as exc_info:
        update_for_workspace("acme", {"generalizer_model": "not-a-real-tag"}, {"generalizer_model"})

    # Names the offending field and value, per the captain's "clear error
    # naming the offending value" requirement - not just a generic 422.
    assert "generalizer_model" in str(exc_info.value)
    assert "not-a-real-tag" in str(exc_info.value)


def test_llm_config_update_accepts_a_model_present_in_the_ollama_catalog(isolated_org_db, monkeypatch):
    from app.services import llm_config_service
    from app.services.llm_config_service import update_for_workspace

    monkeypatch.setattr(
        llm_config_service.ollama_catalog, "list_available_models", lambda force_refresh=False: ["llama3.2:3b"]
    )
    _create_workspace()

    result = update_for_workspace("acme", {"adjuster_model": "llama3.2:3b"}, {"adjuster_model"})

    assert result.adjuster_model == "llama3.2:3b"
    assert result.overrides == {"adjuster_model": "llama3.2:3b"}


@pytest.mark.parametrize("field", ["enricher_model", "normalizer_model", "validator_model"])
def test_llm_config_update_rejects_a_new_role_model_not_in_the_ollama_catalog(isolated_org_db, monkeypatch, field):
    from app.services import llm_config_service
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    monkeypatch.setattr(
        llm_config_service.ollama_catalog, "list_available_models", lambda force_refresh=False: ["qwen2.5:1.5b"]
    )
    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate) as exc_info:
        update_for_workspace("acme", {field: "not-a-real-tag"}, {field})

    assert field in str(exc_info.value)
    assert "not-a-real-tag" in str(exc_info.value)


@pytest.mark.parametrize("field", ["enricher_model", "normalizer_model", "validator_model"])
def test_llm_config_update_accepts_a_new_role_model_present_in_the_ollama_catalog(isolated_org_db, monkeypatch, field):
    from app.services import llm_config_service
    from app.services.llm_config_service import update_for_workspace

    monkeypatch.setattr(
        llm_config_service.ollama_catalog, "list_available_models", lambda force_refresh=False: ["llama3.2:3b"]
    )
    _create_workspace()

    result = update_for_workspace("acme", {field: "llama3.2:3b"}, {field})

    assert getattr(result, field) == "llama3.2:3b"
    assert result.overrides == {field: "llama3.2:3b"}


def test_llm_config_update_validates_against_a_forced_refresh_not_the_stale_cache(isolated_org_db, monkeypatch):
    """A model just installed via `ollama pull` must be acceptable immediately,
    not only after the discovery endpoint's own TTL cache expires."""
    from app.services import llm_config_service
    from app.services.llm_config_service import update_for_workspace

    calls: list[bool] = []

    def _list_available_models(force_refresh=False):
        calls.append(force_refresh)
        return ["qwen2.5:1.5b"]

    monkeypatch.setattr(llm_config_service.ollama_catalog, "list_available_models", _list_available_models)
    _create_workspace()

    update_for_workspace("acme", {"adjuster_model": "qwen2.5:1.5b"}, {"adjuster_model"})

    assert calls == [True]


def test_llm_config_update_reset_to_null_skips_ollama_validation_entirely(isolated_org_db, monkeypatch):
    """Resetting an override to the shipped default must not require Ollama
    to be reachable - there is nothing to validate against a null value."""
    from app.services import llm_config_service
    from app.services.llm_config_service import update_for_workspace

    def _explode(force_refresh=False):
        raise AssertionError("Ollama catalog must not be queried for a null (reset) value")

    monkeypatch.setattr(llm_config_service.ollama_catalog, "list_available_models", _explode)
    _create_workspace()

    result = update_for_workspace("acme", {"generalizer_model": None}, {"generalizer_model"})

    assert "generalizer_model" not in result.overrides


def test_llm_config_update_rejects_when_ollama_is_unreachable(isolated_org_db, monkeypatch):
    from app.services import llm_config_service, ollama_catalog
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    def _unreachable(force_refresh=False):
        raise ollama_catalog.OllamaUnreachableError("Ollama is unreachable at http://127.0.0.1:11434: connection refused")

    monkeypatch.setattr(llm_config_service.ollama_catalog, "list_available_models", _unreachable)
    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate) as exc_info:
        update_for_workspace("acme", {"local_model": "gemma4:e4b"}, {"local_model"})

    assert "unreachable" in str(exc_info.value).lower()


def test_llm_config_update_does_not_validate_external_model_against_ollama(isolated_org_db, monkeypatch):
    """external_model names a LiteLLM-qualified model string (e.g.
    "gemini/gemini-2.5-flash"), never an Ollama tag - it must never be
    checked against the Ollama catalog."""
    from app.services import llm_config_service
    from app.services.llm_config_service import update_for_workspace

    def _explode(force_refresh=False):
        raise AssertionError("external_model must never trigger an Ollama catalog check")

    monkeypatch.setattr(llm_config_service.ollama_catalog, "list_available_models", _explode)
    _create_workspace()

    result = update_for_workspace("acme", {"external_model": "gemini/gemini-2.5-flash"}, {"external_model"})

    assert result.external_model == "gemini/gemini-2.5-flash"


def test_llm_config_update_records_external_provider_resolved_via_litellm(isolated_org_db):
    """Setting external_model also records the matching external_provider,
    resolved via litellm.get_llm_provider - not the registry (A1)."""
    from app.services.llm_config_service import read_for_workspace, update_for_workspace

    _create_workspace()

    result = update_for_workspace("acme", {"external_model": "anthropic/claude-sonnet-5"}, {"external_model"})

    assert result.external_provider == "anthropic"
    assert read_for_workspace("acme").external_provider == "anthropic"


def test_llm_config_update_rejects_an_unqualified_external_model(isolated_org_db):
    """A model LiteLLM cannot place a provider for (no qualifying prefix and
    no bare-name match) is rejected at write time, naming the offending
    value, instead of being accepted and failing later at request time."""
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate) as exc_info:
        update_for_workspace("acme", {"external_model": "llama-3.3-70b"}, {"external_model"})

    assert "llama-3.3-70b" in str(exc_info.value)


def test_llm_config_update_reset_external_model_to_null_clears_external_provider(isolated_org_db):
    from app.services.llm_config_service import read_for_workspace, update_for_workspace

    _create_workspace()
    update_for_workspace("acme", {"external_model": "openai/gpt-4o"}, {"external_model"})

    result = update_for_workspace("acme", {"external_model": None}, {"external_model"})

    assert result.external_provider is None
    assert read_for_workspace("acme").external_provider is None


def test_llm_config_read_leaves_null_external_provider_unguessed(isolated_org_db):
    """A row written before the external_provider column existed (or
    bypassing this write path entirely) is no longer guessed at read time -
    the qualification migration (f7a8b9c0d1e2) is the only place that ever
    backfills such a row, once, from a frozen copy of this same guess."""
    from app.db import llm_config_repo, workspace_repo
    from app.db.session import get_session
    from app.services.llm_config_service import read_for_workspace

    with get_session() as session:
        workspace = workspace_repo.create_workspace(session, "Acme")
        llm_config_repo.upsert_for_workspace(
            session, workspace.id, {"external_model": "claude-sonnet-5"}, {"external_model"}
        )

    result = read_for_workspace("acme")

    assert result.external_provider is None


# ── Per-workspace resolution ──


def test_llm_config_two_workspaces_resolve_independently(isolated_org_db, monkeypatch):
    """A model override in one workspace must never leak into another."""
    from app.config import GENERALIZER_MODEL_NAME
    from app.services import llm_config_service
    from app.services.llm_config_service import read_for_workspace, update_for_workspace
    from app.services.model_backends import MODEL_RUNTIME_SPECS

    monkeypatch.setattr(
        llm_config_service.ollama_catalog, "list_available_models", lambda force_refresh=False: ["gemma4:e4b"]
    )
    _create_workspace("Acme")
    _create_workspace("Beta")

    update_for_workspace("acme", {"generalizer_model": "gemma4:e4b"}, {"generalizer_model"})

    acme = read_for_workspace("acme")
    beta = read_for_workspace("beta")

    assert acme.generalizer_model == "gemma4:e4b"
    assert acme.is_default is False
    assert beta.generalizer_model == MODEL_RUNTIME_SPECS[GENERALIZER_MODEL_NAME].ollama_model
    assert beta.is_default is True


def test_llm_config_two_workspaces_resolve_new_roles_independently(isolated_org_db, monkeypatch):
    """A validator/enricher/normalizer override in one workspace must never
    leak into another - same guarantee slice 1 established for generalizer."""
    from app.config import NORMALIZER_MODEL_NAME
    from app.services import llm_config_service
    from app.services.llm_config_service import read_for_workspace, update_for_workspace
    from app.services.model_backends import MODEL_RUNTIME_SPECS

    monkeypatch.setattr(
        llm_config_service.ollama_catalog, "list_available_models", lambda force_refresh=False: ["gemma4:e4b"]
    )
    _create_workspace("Acme")
    _create_workspace("Beta")

    update_for_workspace("acme", {"normalizer_model": "gemma4:e4b"}, {"normalizer_model"})

    acme = read_for_workspace("acme")
    beta = read_for_workspace("beta")

    assert acme.normalizer_model == "gemma4:e4b"
    assert acme.is_default is False
    assert beta.normalizer_model == MODEL_RUNTIME_SPECS[NORMALIZER_MODEL_NAME].ollama_model
    assert beta.is_default is True


# ── System prompt overrides ──

_PROMPT_FIELDS = (
    "enricher_system_prompt",
    "normalizer_system_prompt",
    "validator_system_prompt",
    "validator_image_system_prompt",
    "adjuster_system_prompt",
    "generalizer_system_prompt",
    "local_model_system_prompt",
)


def test_llm_config_read_defaults_cover_all_prompt_fields(isolated_org_db):
    from app.services.context_adjuster import DEFAULT_ADJUST_SYSTEM_PROMPT, DEFAULT_GENERALIZE_SYSTEM_PROMPT
    from app.services.context_enricher import DEFAULT_SYSTEM_PROMPT as ENRICHER_DEFAULT
    from app.services.llm_config_service import read_for_workspace
    from app.services.llm_router import DEFAULT_SYSTEM_PROMPT as LOCAL_DEFAULT
    from app.services.normalizer import DEFAULT_SYSTEM_PROMPT as NORMALIZER_DEFAULT
    from app.services.validator import DEFAULT_IMAGE_SYSTEM_PROMPT as VALIDATOR_IMAGE_DEFAULT, DEFAULT_SYSTEM_PROMPT as VALIDATOR_DEFAULT

    _create_workspace()

    result = read_for_workspace("acme")

    assert result.enricher_system_prompt == ENRICHER_DEFAULT
    assert result.normalizer_system_prompt == NORMALIZER_DEFAULT
    assert result.validator_system_prompt == VALIDATOR_DEFAULT
    assert result.validator_image_system_prompt == VALIDATOR_IMAGE_DEFAULT
    assert result.adjuster_system_prompt == DEFAULT_ADJUST_SYSTEM_PROMPT
    assert result.generalizer_system_prompt == DEFAULT_GENERALIZE_SYSTEM_PROMPT
    assert result.local_model_system_prompt == LOCAL_DEFAULT
    for field in _PROMPT_FIELDS:
        assert field not in result.overrides


@pytest.mark.parametrize("field", _PROMPT_FIELDS)
def test_llm_config_update_rejects_an_empty_prompt(isolated_org_db, field):
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate) as exc_info:
        update_for_workspace("acme", {field: ""}, {field})

    assert field in str(exc_info.value)
    assert "empty" in str(exc_info.value).lower()


@pytest.mark.parametrize("field", _PROMPT_FIELDS)
def test_llm_config_update_accepts_a_custom_prompt(isolated_org_db, field):
    from app.services.llm_config_service import update_for_workspace

    _create_workspace()

    result = update_for_workspace("acme", {field: "Custom prompt text."}, {field})

    assert getattr(result, field) == "Custom prompt text."
    assert result.overrides == {field: "Custom prompt text."}
    assert result.is_default is False


def test_llm_config_update_prompt_never_queries_ollama(isolated_org_db, monkeypatch):
    """Unlike *_model fields, a prompt has no relationship to what's installed
    on the Ollama host - a prompt update must never trigger a catalog check,
    reachable or not."""
    from app.services import llm_config_service
    from app.services.llm_config_service import update_for_workspace

    def _explode(force_refresh=False):
        raise AssertionError("Ollama catalog must not be queried for a prompt-only update")

    monkeypatch.setattr(llm_config_service.ollama_catalog, "list_available_models", _explode)
    _create_workspace()

    update_for_workspace("acme", {"generalizer_system_prompt": "Custom."}, {"generalizer_system_prompt"})


def test_llm_config_update_reset_prompt_to_null_restores_default(isolated_org_db):
    from app.services.context_adjuster import DEFAULT_GENERALIZE_SYSTEM_PROMPT
    from app.services.llm_config_service import read_for_workspace, update_for_workspace

    _create_workspace()
    update_for_workspace("acme", {"generalizer_system_prompt": "Custom."}, {"generalizer_system_prompt"})

    reset = update_for_workspace("acme", {"generalizer_system_prompt": None}, {"generalizer_system_prompt"})

    assert reset.generalizer_system_prompt == DEFAULT_GENERALIZE_SYSTEM_PROMPT
    assert "generalizer_system_prompt" not in reset.overrides

    stored = read_for_workspace("acme")
    assert stored.generalizer_system_prompt == DEFAULT_GENERALIZE_SYSTEM_PROMPT


def test_llm_config_two_workspaces_resolve_prompts_independently(isolated_org_db):
    """A prompt override in one workspace must never leak into another."""
    from app.services.validator import DEFAULT_SYSTEM_PROMPT as VALIDATOR_DEFAULT
    from app.services.llm_config_service import read_for_workspace, update_for_workspace

    _create_workspace("Acme")
    _create_workspace("Beta")

    update_for_workspace("acme", {"validator_system_prompt": "Acme-only prompt."}, {"validator_system_prompt"})

    acme = read_for_workspace("acme")
    beta = read_for_workspace("beta")

    assert acme.validator_system_prompt == "Acme-only prompt."
    assert acme.is_default is False
    assert beta.validator_system_prompt == VALIDATOR_DEFAULT
    assert beta.is_default is True


# ── Token budget overrides ──


def test_llm_config_read_defaults_cover_token_budgets(isolated_org_db):
    from app.config import (
        DEFAULT_MAX_TOKENS, LOCAL_ATTACHMENT_MAX_TOKENS, OLLAMA_NUM_CTX, REWRITE_MAX_TOKENS,
    )
    from app.services.llm_config_service import read_for_workspace

    _create_workspace()

    result = read_for_workspace("acme")

    assert result.default_max_tokens == DEFAULT_MAX_TOKENS
    assert result.rewrite_max_tokens == REWRITE_MAX_TOKENS
    assert result.ollama_num_ctx == OLLAMA_NUM_CTX
    assert result.local_attachment_max_tokens == LOCAL_ATTACHMENT_MAX_TOKENS
    assert "default_max_tokens" not in result.overrides
    assert "rewrite_max_tokens" not in result.overrides
    assert "ollama_num_ctx" not in result.overrides
    assert "local_attachment_max_tokens" not in result.overrides
    assert result.token_budget_defaults == {
        "default_max_tokens": DEFAULT_MAX_TOKENS,
        "rewrite_max_tokens": REWRITE_MAX_TOKENS,
        "ollama_num_ctx": OLLAMA_NUM_CTX,
        "local_attachment_max_tokens": LOCAL_ATTACHMENT_MAX_TOKENS,
    }


def test_llm_config_token_budget_defaults_survive_an_override(isolated_org_db):
    """token_budget_defaults must always report the shipped/global default,
    even once a workspace has an override in place - it's what a client (the
    dashboard's empty-field-uses-the-default placeholder) needs to show what
    clearing the override restores. The three top-level effective fields
    can't serve that once overridden, since they report the override itself."""
    from app.config import (
        DEFAULT_MAX_TOKENS, LOCAL_ATTACHMENT_MAX_TOKENS, OLLAMA_NUM_CTX, REWRITE_MAX_TOKENS,
    )
    from app.services.llm_config_service import update_for_workspace

    _create_workspace()

    result = update_for_workspace("acme", {"default_max_tokens": 4000}, {"default_max_tokens"})

    assert result.default_max_tokens == 4000
    assert result.token_budget_defaults == {
        "default_max_tokens": DEFAULT_MAX_TOKENS,
        "rewrite_max_tokens": REWRITE_MAX_TOKENS,
        "ollama_num_ctx": OLLAMA_NUM_CTX,
        "local_attachment_max_tokens": LOCAL_ATTACHMENT_MAX_TOKENS,
    }


def test_llm_config_update_accepts_a_valid_token_budget_combination(isolated_org_db):
    from app.services.llm_config_service import read_for_workspace, update_for_workspace

    _create_workspace()

    result = update_for_workspace(
        "acme",
        {"default_max_tokens": 6000, "rewrite_max_tokens": 16000, "ollama_num_ctx": 32000},
        {"default_max_tokens", "rewrite_max_tokens", "ollama_num_ctx"},
    )

    assert result.default_max_tokens == 6000
    assert result.rewrite_max_tokens == 16000
    assert result.ollama_num_ctx == 32000
    assert result.overrides == {
        "default_max_tokens": 6000,
        "rewrite_max_tokens": 16000,
        "ollama_num_ctx": 32000,
    }

    stored = read_for_workspace("acme")
    assert stored.default_max_tokens == 6000


def test_llm_config_update_rejects_an_answer_budget_at_the_measured_truncation_cap(isolated_org_db):
    """1024 is the exact cap config.py records as having truncated ordinary
    answers mid-sentence before DEFAULT_MAX_TOKENS was raised to 4096 - it
    must be refused, not merely discouraged."""
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate) as exc_info:
        update_for_workspace("acme", {"default_max_tokens": 1024}, {"default_max_tokens"})

    assert "default_max_tokens" in str(exc_info.value)
    assert "1024" in str(exc_info.value)


def test_llm_config_update_rejects_a_rewrite_budget_too_close_to_the_answer_budget(isolated_org_db):
    """The rewrite prompt carries the whole raw answer and must keep every
    fact - a rewrite budget barely above the answer budget risks truncating
    the STORED copy, which never self-heals."""
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate) as exc_info:
        update_for_workspace(
            "acme",
            {"default_max_tokens": 4096, "rewrite_max_tokens": 5000},
            {"default_max_tokens", "rewrite_max_tokens"},
        )

    assert "rewrite_max_tokens" in str(exc_info.value)


def test_llm_config_update_rejects_a_context_window_too_close_to_the_rewrite_budget(isolated_org_db):
    """num_ctx bounds the prompt as well as the generation - it has to hold
    the rewrite's own output on top of the prompt carrying the answer being
    rewritten."""
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate) as exc_info:
        update_for_workspace(
            "acme",
            {"rewrite_max_tokens": 8192, "ollama_num_ctx": 10000},
            {"rewrite_max_tokens", "ollama_num_ctx"},
        )

    assert "ollama_num_ctx" in str(exc_info.value)


def test_llm_config_update_rejects_the_measured_incident_configuration(isolated_org_db):
    """The exact failure mode this feature exists to prevent: a generation
    cap low enough to truncate 85% of answers (measured 2026-08-16) must be
    refused outright, not silently accepted."""
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate):
        update_for_workspace("acme", {"default_max_tokens": 300}, {"default_max_tokens"})


def test_llm_config_update_validates_the_relationship_against_existing_stored_values(isolated_org_db):
    """A change to only ONE of the three fields must still be validated
    against the other two as they currently stand - not just against the
    shipped global defaults - so a change that breaks an existing custom
    combination is caught too."""
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    _create_workspace()
    update_for_workspace(
        "acme",
        {"default_max_tokens": 6000, "rewrite_max_tokens": 16000, "ollama_num_ctx": 32000},
        {"default_max_tokens", "rewrite_max_tokens", "ollama_num_ctx"},
    )

    # rewrite_max_tokens alone changes here, but the existing default_max_tokens
    # (6000, from the update above) is what it must be checked against.
    with pytest.raises(InvalidLlmConfigUpdate) as exc_info:
        update_for_workspace("acme", {"rewrite_max_tokens": 7000}, {"rewrite_max_tokens"})

    assert "rewrite_max_tokens" in str(exc_info.value)


def test_llm_config_update_reset_token_budget_to_null_restores_default(isolated_org_db):
    from app.config import DEFAULT_MAX_TOKENS
    from app.services.llm_config_service import read_for_workspace, update_for_workspace

    _create_workspace()
    update_for_workspace("acme", {"default_max_tokens": 4000}, {"default_max_tokens"})

    reset = update_for_workspace("acme", {"default_max_tokens": None}, {"default_max_tokens"})

    assert reset.default_max_tokens == DEFAULT_MAX_TOKENS
    assert "default_max_tokens" not in reset.overrides

    stored = read_for_workspace("acme")
    assert stored.default_max_tokens == DEFAULT_MAX_TOKENS


def test_llm_config_update_reset_never_needs_the_other_two_fields_to_be_valid(isolated_org_db):
    """Resetting an override to null (falling back to the global default) must
    never itself be rejected - a null always resolves to a value the shipped
    defaults already prove is valid together."""
    from app.services.llm_config_service import update_for_workspace

    _create_workspace()
    update_for_workspace(
        "acme",
        {"default_max_tokens": 6000, "rewrite_max_tokens": 16000, "ollama_num_ctx": 32000},
        {"default_max_tokens", "rewrite_max_tokens", "ollama_num_ctx"},
    )

    result = update_for_workspace(
        "acme",
        {"default_max_tokens": None, "rewrite_max_tokens": None, "ollama_num_ctx": None},
        {"default_max_tokens", "rewrite_max_tokens", "ollama_num_ctx"},
    )

    assert result.overrides == {}


def test_llm_config_update_token_budgets_never_queries_ollama(isolated_org_db, monkeypatch):
    """Token budgets have no relationship to what's installed on the Ollama
    host - unlike *_model fields, a budget update must never trigger a
    catalog check."""
    from app.services import llm_config_service
    from app.services.llm_config_service import update_for_workspace

    def _explode(force_refresh=False):
        raise AssertionError("Ollama catalog must not be queried for a token-budget update")

    monkeypatch.setattr(llm_config_service.ollama_catalog, "list_available_models", _explode)
    _create_workspace()

    update_for_workspace(
        "acme",
        {"default_max_tokens": 6000, "rewrite_max_tokens": 16000, "ollama_num_ctx": 32000},
        {"default_max_tokens", "rewrite_max_tokens", "ollama_num_ctx"},
    )


def test_llm_config_two_workspaces_resolve_token_budgets_independently(isolated_org_db):
    """A token budget override in one workspace must never leak into another."""
    from app.config import DEFAULT_MAX_TOKENS
    from app.services.llm_config_service import read_for_workspace, update_for_workspace

    _create_workspace("Acme")
    _create_workspace("Beta")

    update_for_workspace("acme", {"default_max_tokens": 4000}, {"default_max_tokens"})

    acme = read_for_workspace("acme")
    beta = read_for_workspace("beta")

    assert acme.default_max_tokens == 4000
    assert beta.default_max_tokens == DEFAULT_MAX_TOKENS


def test_llm_config_update_rejects_a_token_budget_but_model_field_independent(isolated_org_db, monkeypatch):
    """A model field on the same PUT as a rejected token-budget combination
    must not be silently applied - the whole update is one transaction."""
    from app.services import llm_config_service
    from app.services.llm_config_service import InvalidLlmConfigUpdate, read_for_workspace, update_for_workspace

    monkeypatch.setattr(
        llm_config_service.ollama_catalog, "list_available_models", lambda force_refresh=False: ["gemma4:e4b"]
    )
    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate):
        update_for_workspace(
            "acme",
            {"generalizer_model": "gemma4:e4b", "default_max_tokens": 300},
            {"generalizer_model", "default_max_tokens"},
        )

    stored = read_for_workspace("acme")
    assert stored.is_default is True


def test_llm_config_update_rejects_a_token_budget_but_prompt_field_independent(isolated_org_db):
    from app.services.llm_config_service import InvalidLlmConfigUpdate, read_for_workspace, update_for_workspace

    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate):
        update_for_workspace(
            "acme",
            {"default_max_tokens": 300, "generalizer_system_prompt": "Should not be saved."},
            {"default_max_tokens", "generalizer_system_prompt"},
        )

    stored = read_for_workspace("acme")
    assert stored.is_default is True


def test_llm_config_update_rejects_a_model_but_prompt_field_independent(isolated_org_db, monkeypatch):
    """A prompt field on the same PUT as a rejected *_model field must not be
    silently applied - the whole update is one transaction."""
    from app.services import llm_config_service
    from app.services.llm_config_service import InvalidLlmConfigUpdate, read_for_workspace, update_for_workspace

    monkeypatch.setattr(
        llm_config_service.ollama_catalog, "list_available_models", lambda force_refresh=False: ["qwen2.5:1.5b"]
    )
    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate):
        update_for_workspace(
            "acme",
            {"validator_model": "not-a-real-tag", "validator_system_prompt": "Should not be saved."},
            {"validator_model", "validator_system_prompt"},
        )

    stored = read_for_workspace("acme")
    assert stored.is_default is True


def test_llm_config_update_accepts_a_context_window_at_the_smallest_model_maximum(isolated_org_db):
    from app.config import OLLAMA_NUM_CTX
    from app.services.llm_config_service import update_for_workspace

    _create_workspace()

    result = update_for_workspace("acme", {"ollama_num_ctx": OLLAMA_NUM_CTX}, {"ollama_num_ctx"})

    assert result.ollama_num_ctx == OLLAMA_NUM_CTX


def test_llm_config_update_rejects_a_context_window_past_the_smallest_model_maximum(isolated_org_db):
    """One window is shared by every Ollama-backed role, so the ceiling is the
    SMALLEST maximum among them (qwen2.5:1.5b's 32768, which is what
    OLLAMA_NUM_CTX already equals), not gemma4:e2b's larger one - above it the
    enricher and adjuster cannot honour the window at all. Goes through
    update_for_workspace (the relationship-validation layer), not the bare
    Pydantic schema: a per-field `le=` there would fail before
    _validate_token_budget_overrides ever runs and surface only a generic
    "Input should be less than or equal to N", with no field name and no
    reason - inconsistent with every other rejection this feature raises."""
    from app.config import OLLAMA_NUM_CTX
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate) as exc_info:
        update_for_workspace("acme", {"ollama_num_ctx": OLLAMA_NUM_CTX + 1}, {"ollama_num_ctx"})

    message = str(exc_info.value)
    assert "ollama_num_ctx" in message
    assert str(OLLAMA_NUM_CTX + 1) in message
    assert f"exceeds the ceiling of {OLLAMA_NUM_CTX}" in message
    assert "qwen2.5:1.5b" in message


# --- Alternative drafts (the semantic tie-breaker) --------------------------
#
# Same shape as the token-budget rules above: the RELATIONSHIP between the two
# thresholds has to be judged against the values that will exist AFTER the
# update, not just the ones this particular PUT happens to carry.

def test_llm_config_read_returns_draft_defaults_when_no_row(isolated_org_db):
    from app.config import (
        CACHE_DRAFTS_ENABLED,
        CACHE_DRAFTS_MAX_DELTA,
        CACHE_DRAFTS_MAX_DISTANCE,
    )
    from app.services.llm_config_service import read_for_workspace

    _create_workspace()

    result = read_for_workspace("acme")

    assert result.drafts_enabled is CACHE_DRAFTS_ENABLED
    assert result.drafts_max_distance == CACHE_DRAFTS_MAX_DISTANCE
    assert result.drafts_max_delta == CACHE_DRAFTS_MAX_DELTA
    # The shipped defaults, reported ALWAYS - a client cannot render an
    # "empty uses the default" placeholder from the effective values alone
    # once an override is set.
    assert result.draft_defaults == {
        "drafts_max_distance": CACHE_DRAFTS_MAX_DISTANCE,
        "drafts_max_delta": CACHE_DRAFTS_MAX_DELTA,
    }


def test_llm_config_update_stores_draft_overrides(isolated_org_db):
    from app.services.llm_config_service import update_for_workspace

    _create_workspace()

    result = update_for_workspace(
        "acme",
        {"drafts_enabled": True, "drafts_max_distance": 0.04, "drafts_max_delta": 0.01},
        {"drafts_enabled", "drafts_max_distance", "drafts_max_delta"},
    )

    assert result.drafts_enabled is True
    assert result.drafts_max_distance == 0.04
    assert result.drafts_max_delta == 0.01
    assert result.overrides["drafts_enabled"] is True
    # The defaults keep naming what a reset would restore, not the override.
    assert result.draft_defaults["drafts_max_distance"] != 0.04


def test_llm_config_update_rejects_a_delta_wider_than_its_window(isolated_org_db):
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate) as exc:
        update_for_workspace(
            "acme",
            {"drafts_max_distance": 0.02, "drafts_max_delta": 0.04},
            {"drafts_max_distance", "drafts_max_delta"},
        )

    assert "drafts_max_delta" in str(exc.value)


def test_llm_config_update_rejects_a_window_past_the_validator_skip_distance(isolated_org_db):
    """The alternate draft is shown without a validator call, so the window
    cannot reach past the distance at which the embedding alone is trusted."""
    from app.config import VALIDATOR_SKIP_DISTANCE
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate) as exc:
        update_for_workspace(
            "acme",
            {"drafts_max_distance": VALIDATOR_SKIP_DISTANCE + 0.01},
            {"drafts_max_distance"},
        )

    assert "VALIDATOR_SKIP_DISTANCE" in str(exc.value)


def test_llm_config_update_rejects_a_window_inside_the_trusted_zone_but_past_the_skip(isolated_org_db):
    """The specific hole this ceiling closes: 0.10 is a perfectly ordinary
    trusted-tier distance, and it is also where sibling questions live."""
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate):
        update_for_workspace("acme", {"drafts_max_distance": 0.10}, {"drafts_max_distance"})


def test_llm_config_update_accepts_a_window_exactly_at_the_ceiling(isolated_org_db):
    from app.config import VALIDATOR_SKIP_DISTANCE
    from app.services.llm_config_service import update_for_workspace

    _create_workspace()

    result = update_for_workspace(
        "acme", {"drafts_max_distance": VALIDATOR_SKIP_DISTANCE}, {"drafts_max_distance"}
    )

    assert result.drafts_max_distance == VALIDATOR_SKIP_DISTANCE


def test_llm_config_update_validates_drafts_against_existing_stored_values(isolated_org_db):
    """The rule judges the resulting PAIR. Narrowing the window alone must be
    rejected when a previously stored delta is already wider than the new one."""
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    _create_workspace()
    update_for_workspace(
        "acme",
        {"drafts_max_distance": 0.05, "drafts_max_delta": 0.04},
        {"drafts_max_distance", "drafts_max_delta"},
    )

    with pytest.raises(InvalidLlmConfigUpdate):
        update_for_workspace("acme", {"drafts_max_distance": 0.02}, {"drafts_max_distance"})


def test_llm_config_update_reset_drafts_to_null_restores_defaults(isolated_org_db):
    from app.config import CACHE_DRAFTS_MAX_DELTA, CACHE_DRAFTS_MAX_DISTANCE
    from app.services.llm_config_service import update_for_workspace

    _create_workspace()
    update_for_workspace(
        "acme",
        {"drafts_enabled": True, "drafts_max_distance": 0.04, "drafts_max_delta": 0.01},
        {"drafts_enabled", "drafts_max_distance", "drafts_max_delta"},
    )

    result = update_for_workspace(
        "acme",
        {"drafts_enabled": None, "drafts_max_distance": None, "drafts_max_delta": None},
        {"drafts_enabled", "drafts_max_distance", "drafts_max_delta"},
    )

    assert result.drafts_max_distance == CACHE_DRAFTS_MAX_DISTANCE
    assert result.drafts_max_delta == CACHE_DRAFTS_MAX_DELTA
    assert "drafts_max_distance" not in result.overrides


def test_llm_config_update_drafts_never_queries_ollama(isolated_org_db, monkeypatch):
    """A threshold is not a model name; validating one must not depend on the
    Ollama host being reachable."""
    from app.services import llm_config_service
    from app.services.llm_config_service import update_for_workspace

    def _explode(force_refresh=False):
        raise AssertionError("Ollama must not be consulted for a draft threshold")

    _create_workspace()
    monkeypatch.setattr(llm_config_service.ollama_catalog, "list_available_models", _explode)

    result = update_for_workspace("acme", {"drafts_enabled": True}, {"drafts_enabled"})

    assert result.drafts_enabled is True


def test_llm_config_update_drafts_and_token_budgets_are_independent(isolated_org_db):
    """Touching a draft threshold must not re-validate budgets it isn't
    changing, and vice versa."""
    from app.services.llm_config_service import update_for_workspace

    _create_workspace()
    update_for_workspace("acme", {"drafts_enabled": True}, {"drafts_enabled"})

    result = update_for_workspace("acme", {"default_max_tokens": 2048}, {"default_max_tokens"})

    assert result.default_max_tokens == 2048
    assert result.drafts_enabled is True


def test_llm_config_toggling_drafts_never_validates_thresholds_it_is_not_changing(
    isolated_org_db, monkeypatch
):
    """`drafts_enabled` is a switch, not a threshold.

    Validating the pair on a bare on/off toggle would let a deployment whose
    CACHE_DRAFTS_* env defaults sit outside the bounds reject
    `{"drafts_enabled": true}` over a field the admin never sent and cannot see
    in that request - leaving no way to turn the feature on at all.
    """
    import app.config as config
    from app.services import llm_config_service
    from app.services.llm_config_service import update_for_workspace

    _create_workspace()
    # An env default past the ceiling. Nothing constrains the env var itself.
    monkeypatch.setattr(llm_config_service, "CACHE_DRAFTS_MAX_DISTANCE", 0.20)
    monkeypatch.setattr(config, "CACHE_DRAFTS_MAX_DISTANCE", 0.20)

    result = update_for_workspace("acme", {"drafts_enabled": True}, {"drafts_enabled"})

    assert result.drafts_enabled is True
