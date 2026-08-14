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
        {"external_model": "gemini-2.5-pro", "local_model": "gemma-4-e4b"},
        {"external_model", "local_model"},
    )
    assert first.external_model == "gemini-2.5-pro"
    assert first.local_model == "gemma-4-e4b"
    assert first.overrides == {
        "external_model": "gemini-2.5-pro",
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
    """external_model names a provider model string (e.g. "gemini-2.5-flash"),
    never an Ollama tag - it must never be checked against the Ollama catalog."""
    from app.services import llm_config_service
    from app.services.llm_config_service import update_for_workspace

    def _explode(force_refresh=False):
        raise AssertionError("external_model must never trigger an Ollama catalog check")

    monkeypatch.setattr(llm_config_service.ollama_catalog, "list_available_models", _explode)
    _create_workspace()

    result = update_for_workspace("acme", {"external_model": "gemini-2.5-flash"}, {"external_model"})

    assert result.external_model == "gemini-2.5-flash"


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
