import litellm
import pytest

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
