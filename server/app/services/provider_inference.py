def provider_for_model(model_name: str) -> str:
    model = model_name.strip().lower()
    if model.startswith("gemini-"):
        return "google"
    if model.startswith(("gpt-", "o1-", "o3-", "chatgpt-")):
        return "openai"
    if model.startswith("claude-"):
        return "anthropic"
    raise ValueError(f"Unknown provider for model '{model_name}'")
