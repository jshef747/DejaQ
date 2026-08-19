"""Edit & Save — ingest a human-written answer into the cache.

A user who spots a wrong answer edits it and hits Save. The edited text becomes
the cached answer for that question: served verbatim to the next person in the
department who asks it, with the same +1.0 a thumbs-up would have applied.

The whole point is that the human text REPLACES the model's, so the old answer
must not survive anywhere. It can hide in three places, and each is closed
somewhere different:

- the entry's own `generalized_answer` -> MemoryService.overwrite_answer,
- every alias of that entry, which holds a byte-copy -> the cascade inside
  overwrite_answer,
- the background generalizer still in flight on a miss, which would upsert the
  model's answer back over the human one -> the `authored == "human"` guard in
  tasks/cache_tasks.py and its in-process twin in routers/openai_compat.py.

And one that would corrupt it on READ rather than on write: the context adjuster
paraphrases a cached answer to match the new asker's tone. Left on it would
serve a model's rewording of text a person vouched for, so the serve path skips
it for human entries.

Shaped after escalation._cache_response_id_for_escalation, which is the other
place that builds a cache entry outside the normal chat request.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

from app.services import workspace_overrides
from app.services.chat_messages import extract_pipeline_inputs
from app.services.memory_chromaDB import derive_doc_id, get_memory_service
from app.services.response_registry import compute_messages_hash
from app.services.service_factory import (
    get_context_enricher_service,
    get_normalizer_service,
)

logger = logging.getLogger("dejaq.services.answer_edit")

# The answer a person can type in one sitting, bounded so a pathological client
# cannot push an arbitrarily large blob into ChromaDB metadata. Same budget the
# feedback replay applies to its message array (feedback_service._validate_messages).
MAX_EDITED_ANSWER_BYTES = 256_000

EditStatus = Literal["saved", "created", "not_cached", "message_mismatch"]


@dataclass(frozen=True)
class EditOutcome:
    edit_status: EditStatus
    # The entry the edit actually landed on. Differs from the response_id the
    # client held when the edit was served through an alias (the write is
    # redirected to the root) or when the entry had to be created from a
    # re-derived cache key. The caller returns it so the client can adopt it.
    response_id: str | None = None


def validate_edited_answer(edited_answer: str) -> None:
    """Raises ValueError for an answer that must not reach the cache."""
    if not edited_answer.strip():
        raise ValueError("edited_answer must not be empty")
    if len(edited_answer.encode("utf-8")) > MAX_EDITED_ANSWER_BYTES:
        raise ValueError("edited_answer exceeds maximum size")


def _overwrite_existing(namespace: str, doc_id: str, edited_answer: str) -> str | None:
    """Replace the answer on an entry that already exists. None if it doesn't."""
    try:
        root_id = get_memory_service(namespace).overwrite_answer(doc_id, edited_answer)
    except KeyError:
        return None
    return f"{namespace}:{root_id}"


async def _create_from_messages(
    *, interaction, edited_answer: str, messages: list[dict]
) -> str | None:
    """Build the entry the pipeline never wrote, keyed the way it would have.

    Only reached when there is no entry to overwrite: the cache filter refused
    the query, the background store has not landed yet, or the answer-dependent
    guards on the miss path refused it. A person vouching for an answer is
    better evidence than the filter's three-word minimum, so `cache_filter` is
    deliberately NOT consulted here - that is the one rule Edit & Save is
    allowed to override.

    The derived id can differ from the one the client was holding (the enricher
    is a model, and the planned id was computed from a different enrichment), so
    the caller must return the id this produced rather than the one it was given.
    """
    query, history, _ = extract_pipeline_inputs(messages)
    if not query:
        return None

    slug = interaction.workspace_slug
    try:
        enricher_model = workspace_overrides.workspace_config_override(slug, "enricher_model")
        enricher_prompt = workspace_overrides.workspace_config_override(slug, "enricher_system_prompt")
        enricher_num_ctx = workspace_overrides.workspace_config_override(slug, "ollama_num_ctx")
        enricher_service = (
            get_context_enricher_service(
                model_name=enricher_model, system_prompt=enricher_prompt, num_ctx=enricher_num_ctx
            )
            if (enricher_model or enricher_prompt or enricher_num_ctx)
            else get_context_enricher_service()
        )
        enriched = await enricher_service.enrich(query, history)
    except Exception:
        logger.exception("answer_edit enrich failed")
        enriched = query

    try:
        normalizer_model = workspace_overrides.workspace_config_override(slug, "normalizer_model")
        normalizer_prompt = workspace_overrides.workspace_config_override(slug, "normalizer_system_prompt")
        normalizer_num_ctx = workspace_overrides.workspace_config_override(slug, "ollama_num_ctx")
        normalizer_service = (
            get_normalizer_service(
                model_name=normalizer_model, system_prompt=normalizer_prompt, num_ctx=normalizer_num_ctx
            )
            if (normalizer_model or normalizer_prompt or normalizer_num_ctx)
            else get_normalizer_service()
        )
        clean_query = await normalizer_service.normalize(enriched)
    except Exception:
        logger.exception("answer_edit normalize failed")
        clean_query = enriched

    if not clean_query.strip():
        return None

    namespace = interaction.cache_namespace
    # The re-derived key can land on an entry that DOES exist - the enricher is
    # a model, so this run need not reproduce the id the client was holding, and
    # somebody else may have stored the same question in the meantime. Storing
    # over it would reset score/hit_count/negative_count to 0 (clearing the
    # "first negative deletes" protection) and drop any image_*/file_* metadata
    # not re-supplied, un-gating an attachment entry. Overwrite it instead;
    # store only when the id is genuinely free.
    derived_id = derive_doc_id(clean_query)
    try:
        existing = await asyncio.to_thread(
            _overwrite_existing, namespace, derived_id, edited_answer
        )
        if existing:
            logger.info(
                "answer_edit cache_store status=overwrote_derived namespace=%s doc_id=%s",
                namespace,
                derived_id,
            )
            return existing
        doc_id = await asyncio.to_thread(
            get_memory_service(namespace).store_interaction,
            clean_query,
            edited_answer,
            query,
            slug,
            authored="human",
        )
    except Exception:
        logger.exception("answer_edit cache_store status=failed namespace=%s", namespace)
        return None

    logger.info(
        "answer_edit cache_store status=created namespace=%s doc_id=%s", namespace, doc_id
    )
    return f"{namespace}:{doc_id}"


async def apply_edited_answer(
    *,
    interaction,
    response_id: str | None,
    edited_answer: str,
    messages: list[dict] | None,
) -> EditOutcome:
    """Put `edited_answer` in the cache for the question `interaction` answered.

    `messages` is the client's replay of the exact request that produced the
    answer. It is hash-verified against the interaction record before being
    trusted, and it is only needed for the create-when-absent path.

    Withholding it is meaningful, not merely permitted: the chat client
    withholds it for a turn that carried an image or a file, because the replay
    is blind to the attachment bytes. Creating an entry from it would produce an
    ungated TEXT entry holding an answer about a document nobody attached -
    exactly the poisoning the image and file gates exist to prevent. So an
    attachment turn can only ever overwrite an entry that already exists, whose
    fingerprints overwrite_answer preserves.
    """
    validate_edited_answer(edited_answer)

    # Both, in order, rather than `response_id or interaction.response_id`: a
    # client holding a stale id (its entry evicted, or the header named an entry
    # a store guard then refused) would otherwise skip the overwrite entirely
    # and create a SECOND entry beside the live one the interaction knows about.
    for target_id in (response_id, interaction.response_id):
        if not target_id:
            continue
        namespace, _, doc_id = target_id.partition(":")
        if not doc_id:
            continue
        written = await asyncio.to_thread(
            _overwrite_existing, namespace, doc_id, edited_answer
        )
        if written:
            logger.info(
                "answer_edit status=saved interaction_id=%s response_id=%s",
                interaction.interaction_id,
                written,
            )
            return EditOutcome(edit_status="saved", response_id=written)

    if not messages:
        logger.info(
            "answer_edit status=not_cached reason=no_entry_no_replay interaction_id=%s",
            interaction.interaction_id,
        )
        return EditOutcome(edit_status="not_cached")

    if compute_messages_hash(messages) != interaction.message_hash:
        logger.info(
            "answer_edit status=message_mismatch interaction_id=%s", interaction.interaction_id
        )
        return EditOutcome(edit_status="message_mismatch")

    created = await _create_from_messages(
        interaction=interaction, edited_answer=edited_answer, messages=messages
    )
    if created is None:
        return EditOutcome(edit_status="not_cached")
    return EditOutcome(edit_status="created", response_id=created)
