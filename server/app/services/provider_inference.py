from app.services.provider_registry import provider_for_registered_model


def resolve_provider(model_name: str, stored_provider: str | None) -> str:
    """The provider to use for `model_name` - the ONE place the request path
    makes this decision. Call sites must not reimplement the prefer-then-
    fall-back check themselves.

    Prefers `stored_provider` (a workspace config row's persisted
    `external_provider`, recorded at write time from the model registry -
    see `llm_config_service.py`). Falls back to `provider_for_model` only
    when `stored_provider` is None - true for a row written before the
    `external_provider` column existed (migration `d2e3f4a5b6c7`) and not
    yet resaved, and for `test_provider.py`, where the model is a candidate
    the admin has not saved anywhere yet.
    """
    if stored_provider is not None:
        return stored_provider
    return provider_for_model(model_name)


def provider_for_model(model_name: str) -> str:
    """The provider for a model with no recorded `external_provider`.

    Reached only through `resolve_provider` above. The registry
    (`provider_registry.PROVIDERS`) is consulted first and settles every
    model any live provider actually offers, including the ones whose names
    carry no vendor prefix at all (`grok-4.6`, `deepseek-v4-pro`) or carry
    another vendor's (`openai/gpt-oss-120b`, served by Groq).

    The name-prefix guess below is the fallback for a model the registry
    does not list - a config row naming a model since removed from the
    registry, or a deployment pointing `DEJAQ_EXTERNAL_MODEL` at a newer
    model of a known vendor. It is a guess: it misattributes any model
    served under another vendor's namespace (an OpenRouter
    `anthropic/claude-sonnet-5` would come back `anthropic`), which is why
    the registry is asked first and the column exists at all.
    """
    model = model_name.strip()
    registered = provider_for_registered_model(model)
    if registered is not None:
        return registered
    lowered = model.lower()
    if lowered.startswith("gemini-"):
        return "google"
    if lowered.startswith(("gpt-", "o1-", "o3-", "o4-", "chatgpt-")):
        return "openai"
    if lowered.startswith("claude-"):
        return "anthropic"
    raise ValueError(f"Unknown provider for model '{model_name}'")
