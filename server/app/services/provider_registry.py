"""Single declaration of which providers exist, which models each offers, and
what each model can accept.

The model list is load-bearing at write time, not documentation:
`llm_config_service._provider_for_registered_model` treats `PROVIDERS` as an
allowlist, so a workspace's `external_model` is rejected with 422 when no
provider here offers it, and its provider is recorded from this lookup.
`routers/admin/providers.py` serves the same data publicly as
`GET /admin/v1/providers`, which is where the dashboard's model picker gets
its options. Adding a `ModelSpec` is safe; removing or renaming one breaks
config writes that name it and changes that endpoint's output.

The provider list is mirrored rather than derived: the six places that each
hand-list providers - `external_llm._PROVIDER_CLIENTS`,
`llm_providers.LIVE_PROVIDERS`, `credential_service.SUPPORTED_PROVIDERS`,
`schemas.credentials.ProviderEnum`, the `workspace_provider_credentials` CHECK
constraint, and the dashboard's own `Provider`/`LIVE_PROVIDERS` - are checked
against this one by `tests/test_provider_registry_consistency.py`.

Input kinds are taken from what each provider client in
`app/services/llm_providers/` actually builds: all three clients (google.py,
openai.py, anthropic.py) attach an image or file part unconditionally,
whatever the model, so every model of a live provider gets the same kinds.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class InputKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"


class ClientShape(StrEnum):
    """Which SDK/wire format a live provider's client speaks."""

    GOOGLE_GENAI = "google_genai"
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"
    ANTHROPIC_MESSAGES = "anthropic_messages"


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    input_kinds: frozenset[InputKind] = field(default_factory=lambda: frozenset(InputKind))


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    live: bool
    client_shape: ClientShape | None
    models: tuple[ModelSpec, ...] = ()


# Every model of every live provider accepts text/image/file uniformly -
# see the module docstring for why.
_ALL_KINDS = frozenset(InputKind)

PROVIDERS: dict[str, ProviderSpec] = {
    "google": ProviderSpec(
        key="google",
        live=True,
        client_shape=ClientShape.GOOGLE_GENAI,
        models=(
            ModelSpec("gemini-3.6-flash", "Gemini 3.6 Flash", _ALL_KINDS),
            ModelSpec("gemini-3.5-flash", "Gemini 3.5 Flash", _ALL_KINDS),
            ModelSpec("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", _ALL_KINDS),
            ModelSpec("gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite", _ALL_KINDS),
            ModelSpec("gemini-2.5-pro", "Gemini 2.5 Pro", _ALL_KINDS),
            ModelSpec("gemini-2.5-flash", "Gemini 2.5 Flash", _ALL_KINDS),
            ModelSpec("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite", _ALL_KINDS),
        ),
    ),
    "openai": ProviderSpec(
        key="openai",
        live=True,
        client_shape=ClientShape.OPENAI_CHAT_COMPLETIONS,
        models=(
            ModelSpec("gpt-5.6-sol", "GPT-5.6 Sol", _ALL_KINDS),
            ModelSpec("gpt-5.6-terra", "GPT-5.6 Terra", _ALL_KINDS),
            ModelSpec("gpt-5.6-luna", "GPT-5.6 Luna", _ALL_KINDS),
            ModelSpec("gpt-4.1", "GPT-4.1", _ALL_KINDS),
            ModelSpec("gpt-4.1-mini", "GPT-4.1 mini", _ALL_KINDS),
            ModelSpec("gpt-4o", "GPT-4o", _ALL_KINDS),
            ModelSpec("gpt-4o-mini", "GPT-4o mini", _ALL_KINDS),
        ),
    ),
    "anthropic": ProviderSpec(
        key="anthropic",
        live=True,
        client_shape=ClientShape.ANTHROPIC_MESSAGES,
        models=(
            ModelSpec("claude-fable-5", "Claude Fable 5", _ALL_KINDS),
            ModelSpec("claude-opus-5", "Claude Opus 5", _ALL_KINDS),
            ModelSpec("claude-sonnet-5", "Claude Sonnet 5", _ALL_KINDS),
            ModelSpec("claude-haiku-4-5-20251001", "Claude Haiku 4.5", _ALL_KINDS),
            ModelSpec("claude-opus-4-8", "Claude Opus 4.8", _ALL_KINDS),
            ModelSpec("claude-opus-4-7", "Claude Opus 4.7", _ALL_KINDS),
            ModelSpec("claude-opus-4-6", "Claude Opus 4.6", _ALL_KINDS),
            ModelSpec("claude-sonnet-4-6", "Claude Sonnet 4.6", _ALL_KINDS),
            ModelSpec("claude-sonnet-4-5-20250929", "Claude Sonnet 4.5", _ALL_KINDS),
            ModelSpec("claude-opus-4-5-20251101", "Claude Opus 4.5", _ALL_KINDS),
        ),
    ),
    # Credential-supported only: a workspace can store a key for these, but no
    # client is wired to call them yet.
    "mistral": ProviderSpec(key="mistral", live=False, client_shape=None),
    "cohere": ProviderSpec(key="cohere", live=False, client_shape=None),
    "together": ProviderSpec(key="together", live=False, client_shape=None),
    "groq": ProviderSpec(key="groq", live=False, client_shape=None),
    "fireworks": ProviderSpec(key="fireworks", live=False, client_shape=None),
}


def live_providers() -> set[str]:
    return {key for key, spec in PROVIDERS.items() if spec.live}


def known_providers() -> set[str]:
    return set(PROVIDERS)


def model_ids(provider: str) -> set[str]:
    return {model.id for model in PROVIDERS[provider].models}
