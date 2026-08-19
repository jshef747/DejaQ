from fastapi.testclient import TestClient

from app.services.provider_registry import PROVIDERS


def test_admin_providers_lists_live_providers_and_anthropic_models():
    from app.main import app

    client = TestClient(app)
    resp = client.get("/admin/v1/providers")
    assert resp.status_code == 200

    data = resp.json()
    by_key = {p["key"]: p for p in data["providers"]}

    expected_live = {key for key, spec in PROVIDERS.items() if spec.live}
    actual_live = {key for key, p in by_key.items() if p["live"]}
    assert actual_live == expected_live

    anthropic_spec = PROVIDERS["anthropic"]
    anthropic_resp = by_key["anthropic"]
    assert {m["id"] for m in anthropic_resp["models"]} == {m.id for m in anthropic_spec.models}
    for model_resp in anthropic_resp["models"]:
        spec_model = next(m for m in anthropic_spec.models if m.id == model_resp["id"])
        assert set(model_resp["input_kinds"]) == {kind.value for kind in spec_model.input_kinds}
