import re
from pathlib import Path

import pytest


def _dashboard_external_models() -> list[tuple[str, str]]:
    """Parse dashboard/lib/external-models.ts and return (model_value, provider) pairs.

    Reads the actual source file so this test fails the moment the dashboard
    offers a model the backend doesn't know how to route, instead of relying
    on a hand-picked list that can drift out of sync (see o4-mini).
    """
    ts_path = Path(__file__).resolve().parents[2] / "dashboard" / "lib" / "external-models.ts"
    source = ts_path.read_text()

    block_match = re.search(
        r"EXTERNAL_MODELS:.*?=\s*\{(.*?)\n\};", source, re.DOTALL
    )
    assert block_match, "Could not find EXTERNAL_MODELS block in external-models.ts"
    block = block_match.group(1)

    pairs: list[tuple[str, str]] = []
    for provider_match in re.finditer(r"(\w+):\s*\[(.*?)\]\s*,", block, re.DOTALL):
        provider, entries = provider_match.group(1), provider_match.group(2)
        for value_match in re.finditer(r'value:\s*"([^"]+)"', entries):
            pairs.append((value_match.group(1), provider))

    total_values = len(re.findall(r'value:\s*"([^"]+)"', block))
    assert pairs, "Could not parse any models out of EXTERNAL_MODELS"
    assert len(pairs) == total_values, (
        f"parsed {len(pairs)} (model, provider) pairs but the EXTERNAL_MODELS "
        f"block contains {total_values} 'value: \"...\"' entries - the "
        "provider-block regex silently dropped some entries (e.g. the last "
        "provider block, which has no trailing blank line after it)"
    )
    parsed_providers = {provider for _, provider in pairs}
    for expected_provider in ("google", "openai", "anthropic"):
        assert expected_provider in parsed_providers, (
            f"no models parsed for provider '{expected_provider}' - the "
            "provider-block regex failed to match its block"
        )
    return pairs


def test_every_dashboard_model_maps_to_its_declared_provider():
    from app.services.provider_inference import provider_for_model

    for model, expected_provider in _dashboard_external_models():
        assert provider_for_model(model) == expected_provider, (
            f"dashboard model '{model}' (provider '{expected_provider}') "
            "does not map to that provider in provider_for_model - the "
            "dashboard would offer a model the backend rejects"
        )


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
