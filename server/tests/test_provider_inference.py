"""Name-prefix provider guessing and the stored-provider resolution above it.

The old test that parsed `dashboard/lib/external-models.ts` is gone with the
file itself (piece 1e): the dashboard now fetches its model catalogue from
`GET /admin/v1/providers`, so there is no hand-written list left to drift.
Provider-list drift is covered by `test_provider_registry_consistency.py`.
"""
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


def test_resolve_provider_prefers_the_stored_value_over_the_guess():
    from app.services.provider_inference import resolve_provider

    # "llama-3.3-70b" matches no name-prefix rule at all - if resolve_provider
    # fell through to the guess here it would raise instead of returning this.
    assert resolve_provider("llama-3.3-70b", "groq") == "groq"
    # Even for a model the guess WOULD map correctly, the stored value wins -
    # this is what lets a workspace record a provider a naive prefix guess
    # would misattribute (OpenRouter's "anthropic/claude-sonnet-5", say).
    assert resolve_provider("claude-sonnet-5", "openrouter") == "openrouter"


def test_resolve_provider_falls_back_to_the_guess_when_stored_is_none():
    from app.services.provider_inference import resolve_provider

    assert resolve_provider("claude-sonnet-5", None) == "anthropic"


def test_resolve_provider_raises_when_stored_is_none_and_the_guess_cannot_place_it():
    from app.services.provider_inference import resolve_provider

    with pytest.raises(ValueError, match="Unknown provider"):
        resolve_provider("llama-3.3-70b", None)
