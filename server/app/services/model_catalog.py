"""A projection of `litellm.model_cost` into DejaQ's offerable model catalog.

Computed once per process (`functools.lru_cache`) - the data is static within
a pinned LiteLLM version, so there is no TTL and no refresh parameter, unlike
`ollama_catalog` which proxies a live Ollama server.

Three filters, measured against LiteLLM 1.97.0's `model_cost` (3,054 entries;
plan `dejaq-litellm-migration-plan-v2/report.md` section 2.11):

- `mode == "chat"` only: 3,054 -> 2,344. DejaQ calls `acompletion`; an
  embedding/image-generation/etc. row is not an answer model and offering one
  is a guaranteed runtime failure - this turns a 500 into a 422.
- Deprecated models stay listed (247 of the 2,344), sorted last, carrying
  their `deprecation_date` - hiding them would break a workspace that already
  has one configured.
- `STRUCTURED_CREDENTIAL_PROVIDERS` are excluded below - 587 of the 2,344
  (25%), until that constant is revisited.
"""

from dataclasses import dataclass
from functools import lru_cache

import litellm

# Providers that cannot be authenticated with the single opaque API-key
# string workspace_provider_credentials stores, so DejaQ cannot offer them:
#   - bedrock/azure need a structured multi-field credential (SigV4,
#     endpoint+api-version+deployment) - roadmap Stage 4's config JSON column
#     would fix that but is not built (captain decision, dejaq-litellm-
#     migration-plan-v2-decision-nonstring-credential-providers);
#   - vertex_ai needs a GCP service account, not an API key;
#   - ollama is a local endpoint keyed by base_url, with no API key at all -
#     it is DejaQ's *local* generation backend, never an external provider.
# Remove a provider from this set only once it can actually be authenticated
# to with what workspace_provider_credentials can store. The name is kept for
# its existing importers; membership is "not a single-API-key provider".
STRUCTURED_CREDENTIAL_PROVIDERS = {
    "bedrock",
    "bedrock_converse",
    "azure",
    "azure_ai",
    "vertex_ai",
    "vertex_ai_beta",
    "ollama",
    "ollama_chat",
}


@dataclass(frozen=True)
class CatalogModel:
    id: str
    provider: str
    deprecation_date: str | None = None


def _qualified_id(model_id: str, provider: str) -> str:
    """`provider/model` - the form llm_config_service accepts and stores.

    A bare `model_cost` id like `gemini-2.5-flash` is rejected (or worse,
    mis-resolves to vertex_ai) by write-time validation; only the qualified
    form round-trips to the right provider. Ids that already carry the
    provider prefix are left alone so we never double-prefix (which A7 now
    rejects outright).
    """
    if model_id == provider or model_id.startswith(f"{provider}/"):
        return model_id
    return f"{provider}/{model_id}"


@lru_cache(maxsize=1)
def _catalog() -> tuple[CatalogModel, ...]:
    models = []
    for model_id, spec in litellm.model_cost.items():
        if not isinstance(spec, dict) or spec.get("mode") != "chat":
            continue
        provider = spec.get("litellm_provider")
        if not provider or provider in STRUCTURED_CREDENTIAL_PROVIDERS:
            continue
        models.append(
            CatalogModel(
                id=_qualified_id(model_id, provider),
                provider=provider,
                deprecation_date=spec.get("deprecation_date"),
            )
        )
    # Deprecated last (None sorts before any date string), alphabetical within each half.
    models.sort(key=lambda m: (m.deprecation_date is not None, m.id))
    return tuple(models)


def all_models() -> tuple[CatalogModel, ...]:
    return _catalog()


def provider_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for model in _catalog():
        counts[model.provider] = counts.get(model.provider, 0) + 1
    return counts


def models_for_provider(provider: str) -> tuple[CatalogModel, ...]:
    return tuple(model for model in _catalog() if model.provider == provider)


def is_provider_prefix(name: str) -> bool:
    """True when `name` is a bare LiteLLM provider prefix (e.g. 'gemini',
    'openai'). Kept here because this module is the one allowed to import
    litellm (tests/test_litellm_single_import.py)."""
    return name in litellm.provider_list


def resolve_provider(model: str) -> str:
    """The LiteLLM provider `model` resolves to, or raise ValueError.

    Deliberately does not consult `_catalog()` / `litellm.model_cost` at all
    (assertion 4, plan section 2.11): a model LiteLLM has never heard of must
    still resolve here, so `llm_config_service` can accept it.
    """
    try:
        _, provider, _, _ = litellm.get_llm_provider(model)
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    if provider not in litellm.provider_list:
        raise ValueError(f"'{model}' resolved to '{provider}', which is not a known LiteLLM provider.")
    return provider
