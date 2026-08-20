"""Single declaration of which providers exist, which models each offers, and
what each model can accept.

The model list is load-bearing at write time, not documentation:
`llm_config_service` treats `PROVIDERS` as an allowlist through
`provider_for_registered_model` below, so a workspace's `external_model` is
rejected with 422 when no provider here offers it, and its provider is
recorded from this lookup. `provider_inference.provider_for_model` consults
the same lookup before its name-prefix guess, so a model listed here never
depends on its name matching a vendor prefix.
`routers/admin/providers.py` serves the same data publicly as
`GET /admin/v1/providers`, which is where the dashboard's model picker gets
its options. Adding a `ModelSpec` is safe; removing or renaming one breaks
config writes that name it and changes that endpoint's output.

The provider list is mirrored rather than derived, so four other places carry
their own copy - `llm_providers.LIVE_PROVIDERS` (migration stage L6:
`external_llm._PROVIDER_CLIENTS` now builds one `LiteLLMTransportClient` per
key in that set, so it is no longer an independent mirror itself),
`credential_service.SUPPORTED_PROVIDERS`, `schemas.credentials.ProviderEnum`,
and the dashboard's own `Provider`/`LIVE_PROVIDERS`. All are checked against
this one by `tests/test_provider_registry_consistency.py`. The
`workspace_provider_credentials` CHECK constraint used to be a sixth mirror;
it was dropped (migration e5f6a7b8c9d0) because every new provider cost a
full SQLite table rebuild, and this registry already validates provider names
in Python.

Input kinds are NOT uniform across every live provider, even though every
live provider now shares one client (`llm_providers.litellm_transport`,
migration stage L6) that attaches an image or file part unconditionally
whatever the model. DeepSeek's models take text only, and Groq's vision
support is per-model, not per-provider - most Groq models are text-only.
`input_kinds` is set per `ModelSpec` for exactly this reason and enforced
before the client is ever called; do not assume every model of a live
provider matches its neighbours.
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
    # None for a provider whose row carries no override (OpenAI itself: the
    # `openai` SDK's own default). Sourced into the client by
    # `external_llm._PROVIDER_CLIENTS`, never hardcoded at the client call site.
    base_url: str | None = None


# google/openai/anthropic accept text/image/file uniformly across every
# model - see the module docstring for why that stops being true below.
_ALL_KINDS = frozenset(InputKind)
_TEXT_ONLY = frozenset({InputKind.TEXT})
_TEXT_IMAGE = frozenset({InputKind.TEXT, InputKind.IMAGE})

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
    "xai": ProviderSpec(
        key="xai",
        live=True,
        client_shape=ClientShape.OPENAI_CHAT_COMPLETIONS,
        base_url="https://api.x.ai/v1",
        # Text models only (excludes grok-imagine-* image/video generation and
        # grok-voice-* audio models - not chat-completions models). All accept
        # image input (jpg/png); none accept file input. docs.x.ai/docs/models
        models=(
            ModelSpec("grok-4.6", "Grok 4.6", _TEXT_IMAGE),
            ModelSpec("grok-4.5", "Grok 4.5", _TEXT_IMAGE),
            ModelSpec("grok-4.3", "Grok 4.3", _TEXT_IMAGE),
            ModelSpec("grok-4.20-0309-reasoning", "Grok 4.20 (Reasoning)", _TEXT_IMAGE),
            ModelSpec("grok-4.20-0309-non-reasoning", "Grok 4.20 (Non-Reasoning)", _TEXT_IMAGE),
            ModelSpec("grok-4.20-multi-agent-0309", "Grok 4.20 (Multi-Agent)", _TEXT_IMAGE),
            ModelSpec("grok-build-0.1", "Grok Build 0.1", _TEXT_IMAGE),
        ),
    ),
    "deepseek": ProviderSpec(
        key="deepseek",
        live=True,
        client_shape=ClientShape.OPENAI_CHAT_COMPLETIONS,
        base_url="https://api.deepseek.com",
        # Text only - neither model takes image or file input.
        # api-docs.deepseek.com/quick_start/pricing
        models=(
            ModelSpec("deepseek-v4-flash", "DeepSeek V4 Flash", _TEXT_ONLY),
            ModelSpec("deepseek-v4-pro", "DeepSeek V4 Pro", _TEXT_ONLY),
        ),
    ),
    "groq": ProviderSpec(
        key="groq",
        live=True,
        client_shape=ClientShape.OPENAI_CHAT_COMPLETIONS,
        base_url="https://api.groq.com/openai/v1",
        # Vision is per-model, not per-provider: only qwen/qwen3.6-27b takes
        # image input on GroqCloud today. console.groq.com/docs/models,
        # console.groq.com/docs/vision. No model takes file input.
        models=(
            ModelSpec("openai/gpt-oss-120b", "GPT-OSS 120B (Groq)", _TEXT_ONLY),
            ModelSpec("openai/gpt-oss-20b", "GPT-OSS 20B (Groq)", _TEXT_ONLY),
            ModelSpec("groq/compound", "Groq Compound", _TEXT_ONLY),
            ModelSpec("groq/compound-mini", "Groq Compound Mini", _TEXT_ONLY),
            ModelSpec("qwen/qwen3.6-27b", "Qwen3.6 27B (Groq, vision)", _TEXT_IMAGE),
        ),
    ),
    # Credential-supported only: a workspace can store a key for these, but no
    # client is wired to call them yet.
    "mistral": ProviderSpec(key="mistral", live=False, client_shape=None),
    "cohere": ProviderSpec(key="cohere", live=False, client_shape=None),
    "together": ProviderSpec(key="together", live=False, client_shape=None),
    "fireworks": ProviderSpec(key="fireworks", live=False, client_shape=None),
}


def live_providers() -> set[str]:
    return {key for key, spec in PROVIDERS.items() if spec.live}


def known_providers() -> set[str]:
    return set(PROVIDERS)


def model_ids(provider: str) -> set[str]:
    return {model.id for model in PROVIDERS[provider].models}


def provider_for_registered_model(model_id: str) -> str | None:
    """Which provider lists `model_id`, or None if none does.

    The one registry lookup: `llm_config_service` uses it to validate and
    record `external_provider` at write time, and `provider_inference`
    consults it before falling back to its name-prefix guess, so a model
    listed here is placed by the list rather than by its name.
    """
    for provider_key, spec in PROVIDERS.items():
        if any(model.id == model_id for model in spec.models):
            return provider_key
    return None
