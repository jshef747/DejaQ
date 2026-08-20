"""qualify external_model with its LiteLLM provider prefix

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-08-20 00:00:00.000000

LiteLLM will not guess a provider from a bare model name. Verified directly
against LiteLLM 1.97.0: 12 of DejaQ's 38 shipped models raise BadRequestError
from a bare name, and 9 more silently resolve to the WRONG provider - every
`gemini-*` model resolves to `vertex_ai`, not `gemini` (Vertex wants a GCP
service account, not the plain API key DejaQ stores), and the two
Groq-served `gpt-oss` models resolve to `openai`, not `groq`. Going forward,
`external_model` is written already qualified with its LiteLLM provider
prefix (app.services.llm_config_service). This migration is the one-time
backfill for every row saved before that existed.

The backfill rule is UNCONDITIONAL prefixing, even when the stored model
already contains a slash: `f"{litellm_key}/{external_model}"`. A naive
`if "/" not in model` guard looks obviously right and is wrong - measured:
`litellm.get_llm_provider("groq/compound")` returns provider `groq` and
model `compound`, the wrong model name on the wire. The correct stored form
is `groq/groq/compound`, which round-trips to model `groq/compound`. Same
trap for `groq/openai/gpt-oss-120b` (correct) vs `openai/gpt-oss-120b`
(silently routed to OpenAI instead of Groq).

Frozen copies below, same discipline as d2e3f4a5b6c7's own docstring: do not
import the live app function here - it may be changed or removed by later
code, and this migration must keep reproducing the same backfill on a fresh
database regardless.

Three row shapes:
  1. `external_model` AND `external_provider` both set: qualify in place
     using the stored provider.
  2. `external_model` set, `external_provider` NULL (written before
     d2e3f4a5b6c7 and never resaved): apply d2e3f4a5b6c7's own frozen guess
     first. If it places the model, qualify AND backfill `external_provider`
     to the guessed value - a later migration stage removes the app's
     request-time guess fallback entirely, so a row left with a null
     `external_provider` here would 422 on every hard query from then on
     despite now having a qualified model.
  3. `external_model` set, `external_provider` NULL, and the guess cannot
     place it (anything outside gemini-/gpt-/o1-/o3-/o4-/chatgpt-/claude-,
     e.g. `grok-4.6`): LEFT UNCHANGED and logged. A wrong guess here is a
     silent misroute; refusing is correct - it becomes a 422 naming the fix
     at request time instead of a guess.
"""
import logging

from alembic import op
import sqlalchemy as sa


revision = "f7a8b9c0d1e2"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.dejaq.qualify_external_model")

# Frozen copy of app.services.llm_providers.litellm_transport._LITELLM_PROVIDER_KEYS
# as it read at migration authorship time. DejaQ's provider keys are not all
# LiteLLM's: `google`, `together` and `fireworks` are not real LiteLLM
# provider names (verified against litellm.provider_list); LiteLLM's names
# are `gemini`, `together_ai` and `fireworks_ai`. The other DejaQ providers
# match identity.
_LITELLM_KEY = {
    "google": "gemini",
    "together": "together_ai",
    "fireworks": "fireworks_ai",
}

# The full set of first-path-segments this migration's upgrade() can ever
# produce, for downgrade()'s "strip only a known LiteLLM key" rule: the three
# translated values above, plus every other DejaQ provider key, which map to
# themselves. Frozen at DejaQ's provider set as of migration authorship
# (app.services.provider_registry.PROVIDERS keys) for the same reason as the
# map above - do not import the live registry here.
_KNOWN_LITELLM_PREFIXES = frozenset(_LITELLM_KEY.values()) | {
    "openai", "anthropic", "xai", "deepseek", "groq", "mistral", "cohere",
}


def _guess_provider(model_name: str) -> str | None:
    """Frozen copy of d2e3f4a5b6c7's own `_provider_for_model`. Do not import
    the live app function here, for the same reason that migration didn't."""
    model = model_name.strip().lower()
    if model.startswith("gemini-"):
        return "google"
    if model.startswith(("gpt-", "o1-", "o3-", "o4-", "chatgpt-")):
        return "openai"
    if model.startswith("claude-"):
        return "anthropic"
    return None


def _qualify(model_name: str, provider: str) -> str:
    return f"{_LITELLM_KEY.get(provider, provider)}/{model_name}"


def _configs_table():
    return sa.table(
        "workspace_llm_configs",
        sa.column("workspace_id", sa.Integer()),
        sa.column("external_model", sa.String()),
        sa.column("external_provider", sa.String()),
    )


def upgrade() -> None:
    bind = op.get_bind()
    configs_table = _configs_table()
    rows = bind.execute(
        sa.select(
            configs_table.c.workspace_id,
            configs_table.c.external_model,
            configs_table.c.external_provider,
        ).where(configs_table.c.external_model.isnot(None))
    ).fetchall()

    for workspace_id, external_model, external_provider in rows:
        provider = external_provider
        if provider is None:
            provider = _guess_provider(external_model)
            if provider is None:
                logger.warning(
                    "workspace_id=%s external_model=%r has no external_provider "
                    "and cannot be placed by the frozen prefix guess - left "
                    "unqualified. It will 422 at request time naming the fix.",
                    workspace_id, external_model,
                )
                continue

        qualified = _qualify(external_model, provider)
        bind.execute(
            configs_table.update()
            .where(configs_table.c.workspace_id == workspace_id)
            .values(external_model=qualified, external_provider=provider)
        )


def downgrade() -> None:
    bind = op.get_bind()
    configs_table = _configs_table()
    rows = bind.execute(
        sa.select(configs_table.c.workspace_id, configs_table.c.external_model).where(
            configs_table.c.external_model.isnot(None)
        )
    ).fetchall()

    for workspace_id, external_model in rows:
        prefix, sep, rest = external_model.partition("/")
        if not sep or prefix not in _KNOWN_LITELLM_PREFIXES:
            continue
        bind.execute(
            configs_table.update()
            .where(configs_table.c.workspace_id == workspace_id)
            .values(external_model=rest)
        )
