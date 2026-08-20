"""Guard against a future LiteLLM release renaming a provider key out from
under DejaQ's qualified model names. Parametrised over all 38 models DejaQ's
six live providers ship today (app.services.provider_registry.PROVIDERS);
each qualified name (provider prefix + model, the same construction the
qualification migration f7a8b9c0d1e2 backfills) must resolve, through
LiteLLM itself, to the provider that produced it.
"""
import litellm
import pytest

from app.services.llm_providers.litellm_transport import _litellm_key
from app.services.provider_registry import PROVIDERS

pytestmark = pytest.mark.no_model

_CASES = [
    (provider_key, model.id)
    for provider_key, spec in PROVIDERS.items()
    if spec.live
    for model in spec.models
]


@pytest.mark.parametrize("provider_key,model_id", _CASES, ids=[f"{p}:{m}" for p, m in _CASES])
def test_qualified_model_resolves_to_its_provider(provider_key, model_id):
    qualified = f"{_litellm_key(provider_key)}/{model_id}"

    _model, resolved_provider, *_ = litellm.get_llm_provider(qualified)

    assert resolved_provider == _litellm_key(provider_key)


def test_thirty_eight_models_are_covered():
    assert len(_CASES) == 38
