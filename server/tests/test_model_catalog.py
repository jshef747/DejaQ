import litellm
import pytest
from fastapi.testclient import TestClient

from app.services import model_catalog
from app.services.model_catalog import STRUCTURED_CREDENTIAL_PROVIDERS

pytestmark = pytest.mark.no_model


def test_catalog_excludes_a_non_chat_model():
    """mode == "chat" only - an embedding/image-generation row is not an
    answer model and offering one is a guaranteed runtime failure."""
    ids = {m.id for m in model_catalog.all_models()}
    non_chat = [k for k, v in litellm.model_cost.items() if isinstance(v, dict) and v.get("mode") != "chat"]
    assert non_chat, "fixture assumption: litellm.model_cost has non-chat entries"
    assert non_chat[0] not in ids


def test_catalog_keeps_a_deprecated_model_and_sorts_it_last():
    models = model_catalog.all_models()
    deprecated = [m for m in models if m.deprecation_date is not None]
    assert deprecated, "fixture assumption: litellm.model_cost has deprecated chat models"

    last_non_deprecated_index = max(i for i, m in enumerate(models) if m.deprecation_date is None)
    first_deprecated_index = min(i for i, m in enumerate(models) if m.deprecation_date is not None)
    assert first_deprecated_index > last_non_deprecated_index


def test_catalog_excludes_structured_credential_providers():
    """bedrock/azure and siblings are filtered at the source - workspace_provider_credentials
    stores one opaque string per provider and cannot hold SigV4 or endpoint+api-version+deployment."""
    providers_present = {m.provider for m in model_catalog.all_models()}
    assert providers_present.isdisjoint(STRUCTURED_CREDENTIAL_PROVIDERS)


def test_catalog_provider_counts_and_models_endpoints():
    from app.main import app

    client = TestClient(app)

    providers_resp = client.get("/admin/v1/model-catalog/providers")
    assert providers_resp.status_code == 200
    providers = {p["key"]: p["model_count"] for p in providers_resp.json()["providers"]}
    assert providers, "expected a non-empty provider list"
    assert STRUCTURED_CREDENTIAL_PROVIDERS.isdisjoint(providers)

    some_key = next(iter(providers))
    models_resp = client.get(f"/admin/v1/model-catalog/providers/{some_key}/models")
    assert models_resp.status_code == 200
    body = models_resp.json()
    assert body["provider"] == some_key
    assert len(body["models"]) == providers[some_key]

    missing = client.get("/admin/v1/model-catalog/providers/not-a-real-provider/models")
    assert missing.status_code == 404


def test_old_admin_providers_endpoint_is_gone():
    """A1c: the old GET /admin/v1/providers endpoint (provider_registry.py's
    shape) is deleted now that the dashboard picker (A1b) no longer calls it -
    model-catalog's own endpoints, covered above, are the only surface left."""
    from app.main import app

    client = TestClient(app)
    resp = client.get("/admin/v1/providers")
    assert resp.status_code == 404


# ── Write-time validation (llm_config_service._validate_and_resolve_external_model) ──


def _create_workspace(name: str = "Acme") -> None:
    from app.db import workspace_repo
    from app.db.session import get_session

    with get_session() as session:
        workspace_repo.create_workspace(session, name)


def test_bare_grok_model_is_rejected_naming_the_qualified_fix(isolated_org_db):
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate) as exc_info:
        update_for_workspace("acme", {"external_model": "grok-4.6"}, {"external_model"})

    assert "xai/grok-4.6" in str(exc_info.value)


def test_hand_typed_bedrock_model_is_rejected_even_though_it_never_came_from_a_picker(isolated_org_db):
    """Assertion 3 is the reason the structured-credential filter can't be bypassed:
    without it, a free-typed 'bedrock/...' model walks straight around the catalog filter."""
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_workspace

    _create_workspace()

    with pytest.raises(InvalidLlmConfigUpdate) as exc_info:
        update_for_workspace(
            "acme", {"external_model": "bedrock/anthropic.claude-3"}, {"external_model"}
        )

    assert "bedrock" in str(exc_info.value)


def test_model_absent_from_model_cost_is_accepted_not_rejected(isolated_org_db):
    """Assertion 4: NOT "is this model in litellm.model_cost" - groq/compound is absent
    from model_cost and DejaQ ships it today. Rejecting unknown models would break the
    product the day a vendor ships a new one, so an unknown-but-addressable model must
    still be accepted. This is the assertion most likely to be broken by a well-meaning
    later change that tries to validate against the catalog."""
    assert "groq/groq/compound" not in litellm.model_cost

    from app.services.llm_config_service import update_for_workspace

    _create_workspace()

    result = update_for_workspace(
        "acme", {"external_model": "groq/groq/compound"}, {"external_model"}
    )

    assert result.external_model == "groq/groq/compound"
    assert result.external_provider == "groq"


def test_credential_upsert_for_a_structured_credential_provider_is_rejected(monkeypatch):
    """The structured-credential check applies wherever a provider key can be
    written, not just the catalog - this is what stops a direct API call from
    saving a single-string credential for a provider that needs more than one."""
    from cryptography.fernet import Fernet

    import app.config as config
    from app.services.credential_service import CredentialService

    monkeypatch.setattr(config, "CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode(), raising=False)

    with pytest.raises(ValueError, match="structured credential"):
        CredentialService().upsert(session=None, workspace_id=1, provider="azure", raw_key="secret")
