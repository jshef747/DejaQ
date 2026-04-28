import pytest


@pytest.mark.parametrize(
    ("model", "provider"),
    [
        ("gemini-2.5-flash", "google"),
        ("Gemini-2.5-flash", "google"),
        ("gpt-4o", "openai"),
        ("o1-mini", "openai"),
        ("o3-mini", "openai"),
        ("chatgpt-4o-latest", "openai"),
        ("claude-sonnet-4-5", "anthropic"),
    ],
)
def test_provider_for_model_maps_known_prefixes_case_insensitively(model, provider):
    from app.services.provider_inference import provider_for_model

    assert provider_for_model(model) == provider


def test_provider_for_model_raises_for_unmapped_model():
    from app.services.provider_inference import provider_for_model

    with pytest.raises(ValueError, match="Unknown provider"):
        provider_for_model("mystery-model")
