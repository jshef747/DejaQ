"""Guard against a future LiteLLM release renaming a provider key out from
under DejaQ's qualified model names. Parametrised over all 38 models DejaQ's
six live providers ship today (the frozen legacy table
`app.services.llm_config_service._LEGACY_BARE_MODEL_PROVIDERS`, all that
survives of the deleted `provider_registry.PROVIDERS` after A1c); each
qualified name (provider prefix + model, the same construction the
qualification migration f7a8b9c0d1e2 backfills) must resolve, through
LiteLLM itself, to the provider that produced it.
"""
import litellm
import pytest

from app.services.llm_config_service import _LEGACY_BARE_MODEL_PROVIDERS
from app.services.llm_providers.litellm_transport import _litellm_key

pytestmark = pytest.mark.no_model

_CASES = [(provider_key, model_id) for model_id, provider_key in _LEGACY_BARE_MODEL_PROVIDERS.items()]


@pytest.mark.parametrize("provider_key,model_id", _CASES, ids=[f"{p}:{m}" for p, m in _CASES])
def test_qualified_model_resolves_to_its_provider(provider_key, model_id):
    qualified = f"{_litellm_key(provider_key)}/{model_id}"

    _model, resolved_provider, *_ = litellm.get_llm_provider(qualified)

    assert resolved_provider == _litellm_key(provider_key)


def test_thirty_eight_models_are_covered():
    assert len(_CASES) == 38
