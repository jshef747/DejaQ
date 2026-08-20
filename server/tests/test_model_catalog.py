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


def test_existing_admin_providers_endpoint_response_shape_is_unchanged():
    """A1a is additive only - the old GET /admin/v1/providers endpoint (which
    the dashboard currently calls) must keep serving provider_registry.PROVIDERS,
    unchanged, until A1b switches the dashboard over."""
    from app.main import app
    from app.services.provider_registry import PROVIDERS

    client = TestClient(app)
    resp = client.get("/admin/v1/providers")
    assert resp.status_code == 200

    data = resp.json()
    assert set(data.keys()) == {"providers"}
    by_key = {p["key"]: p for p in data["providers"]}
    assert set(by_key) == set(PROVIDERS)
    for key, spec in PROVIDERS.items():
        entry = by_key[key]
        assert set(entry.keys()) == {"key", "live", "client_shape", "models"}
        assert entry["live"] == spec.live
        assert entry["client_shape"] == (spec.client_shape.value if spec.client_shape else None)
        assert {m["id"] for m in entry["models"]} == {m.id for m in spec.models}
