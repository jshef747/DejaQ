def resolve_provider(model_name: str, stored_provider: str | None) -> str:
    """The provider to use for `model_name` - the ONE place the request path
    makes this decision. Call sites must not reimplement the prefer-then-
    fall-back check themselves.

    Prefers `stored_provider` (a workspace config row's persisted
    `external_provider`, recorded at write time from the model registry -
    see `llm_config_service.py`). Falls back to the `provider_for_model`
    name-prefix guess only when `stored_provider` is None - true for a row
    written before the `external_provider` column existed (migration
    `d2e3f4a5b6c7`) and not yet resaved.
    """
    if stored_provider is not None:
        return stored_provider
    return provider_for_model(model_name)


def provider_for_model(model_name: str) -> str:
    """Guess a model's provider from its name prefix.

    BACKFILL/FALLBACK ONLY. A config row now records its provider directly
    in `external_provider` (workspace_llm_configs, migration d2e3f4a5b6c7),
    validated against `provider_registry` at write time - this guess is
    reached only through `resolve_provider` above, for a row whose column is
    still NULL. It breaks for any provider serving someone else's models
    (Groq's `llama-3.3-70b` matches nothing here; OpenRouter's
    `anthropic/claude-sonnet-5` would be misattributed to Anthropic), which
    is exactly why the column and the registry exist.
    """
    model = model_name.strip().lower()
    if model.startswith("gemini-"):
        return "google"
    if model.startswith(("gpt-", "o1-", "o3-", "o4-", "chatgpt-")):
        return "openai"
    if model.startswith("claude-"):
        return "anthropic"
    raise ValueError(f"Unknown provider for model '{model_name}'")
