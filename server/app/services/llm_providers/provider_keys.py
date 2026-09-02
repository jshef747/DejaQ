"""DejaQ <-> LiteLLM provider-key mapping, and the one predicate deciding
whether a DejaQ provider key is usable end to end.

Split out of `litellm_transport.py` / `llm_config_service.py` so both (and
`llm_providers/__init__.py`) can share one map and one predicate without a
circular import - this module imports nothing from either.
"""

import litellm

from app.services.model_catalog import STRUCTURED_CREDENTIAL_PROVIDERS

# DejaQ's provider keys are not all LiteLLM's. `google`, `together` and
# `fireworks` are not real LiteLLM provider names (verified against
# litellm.provider_list); LiteLLM's names are `gemini`, `together_ai` and
# `fireworks_ai`. Every other DejaQ provider key matches LiteLLM's own.
LITELLM_PROVIDER_KEYS = {
    "google": "gemini",
    "together": "together_ai",
    "fireworks": "fireworks_ai",
}

# Inverse map: LiteLLM's own provider key -> DejaQ's provider key.
DEJAQ_PROVIDER_KEYS = {litellm_key: dejaq_key for dejaq_key, litellm_key in LITELLM_PROVIDER_KEYS.items()}


def litellm_key(provider: str) -> str:
    """DejaQ's `provider` key, translated into LiteLLM's own namespace."""
    return LITELLM_PROVIDER_KEYS.get(provider, provider)


def is_usable_provider(provider: str) -> bool:
    """True when a DejaQ provider key authenticates with a single API-key
    string and LiteLLM can address it - i.e. it maps (through the rename
    table above) into `litellm.provider_list` and is not one of
    `STRUCTURED_CREDENTIAL_PROVIDERS` (Bedrock/Azure need more than one
    credential field, which workspace_provider_credentials cannot store).
    """
    mapped = litellm_key(provider)
    return mapped in litellm.provider_list and mapped not in STRUCTURED_CREDENTIAL_PROVIDERS
