from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Literal

from pydantic import BaseModel

from app.config import OLLAMA_TIMEOUT_SECONDS
from app.db.session import get_session
from app.schemas.chat import ExternalLLMRequest
from app.schemas.feedback import EscalatedResponse
from app.services import cache_filter, llm_config_service, workspace_overrides
from app.services.chat_messages import extract_pipeline_inputs
from app.services.credential_service import CredentialService
from app.services.external_llm import ExternalLLMService
from app.services.memory_chromaDB import get_memory_service, is_human_authored
from app.services.request_logger import request_logger
from app.services.response_registry import response_registry
from app.services.service_factory import (
    get_context_adjuster_service,
    get_context_enricher_service,
    get_llm_router_service,
    get_normalizer_service,
)
from app.utils.exceptions import ExternalLLMAuthError, ExternalLLMError, ExternalLLMTimeoutError

logger = logging.getLogger("dejaq.services.escalation")


class EscalationResult(BaseModel):
    escalated_response: EscalatedResponse | None = None
    escalation_status: Literal[
        "answered",
        "no_further_escalation",
        "no_credential",
        "provider_error",
        "timeout",
    ]


def _doc_id(clean_query: str) -> str:
    return hashlib.sha256(clean_query.encode()).hexdigest()[:16]


# Both lifted into services/workspace_overrides.py so answer_edit.py can share
# them rather than keep a second copy that drifts. Aliased rather than renamed
# at every call site below - the names are private to this module either way.
_effective_default_max_tokens = workspace_overrides.effective_default_max_tokens
_workspace_config_override = workspace_overrides.workspace_config_override


def _entry_is_attachment_anchored(meta: dict | None) -> bool:
    if not meta:
        return False
    return bool(
        meta.get("image_kind")
        or meta.get("image_text")
        or meta.get("image_dhash")
        or meta.get("image_clip")
        or meta.get("file_sha")
        or meta.get("file_kind")
    )


async def _parent_is_attachment_anchored(interaction) -> bool:
    # Only a cache-served parent can be attachment-anchored: both escalation
    # branches store plain-text answers, so a "local"/"external" parent's own
    # cache entry (if any) never carries image/file metadata - no need to walk
    # further up the chain.
    if interaction.served_tier != "cache" or not interaction.response_id:
        return False
    namespace, _, doc_id = interaction.response_id.partition(":")
    if not doc_id:
        return False
    try:
        meta = await asyncio.to_thread(get_memory_service(namespace).get_entry_metadata, doc_id)
    except Exception:
        logger.exception(
            "feedback_escalation attachment_check failed interaction_id=%s - refusing to cache",
            interaction.interaction_id,
        )
        return True
    return _entry_is_attachment_anchored(meta)


async def _store_escalation_cache_entry(
    *,
    clean_query: str,
    answer: str,
    original_query: str,
    tenant_id: str,
    cache_namespace: str,
) -> None:
    doc_id = _doc_id(clean_query)
    try:
        # Same guard the two background store paths carry (tasks/cache_tasks.py,
        # openai_compat.py): a person wrote the answer at this id through Edit &
        # Save, and the model's re-answer must not replace their text. Reachable
        # here even when the escalating turn was never cached itself - the edit
        # creates the entry at the same id, derived from the query alone.
        memory = get_memory_service(cache_namespace)
        if is_human_authored(memory, doc_id):
            logger.info(
                "feedback_escalation cache_store status=skipped reason=human_authored namespace=%s doc_id=%s",
                cache_namespace,
                doc_id,
            )
            return
        generalizer_model = _workspace_config_override(tenant_id, "generalizer_model")
        generalizer_prompt = _workspace_config_override(tenant_id, "generalizer_system_prompt")
        rewrite_max_tokens = _workspace_config_override(tenant_id, "rewrite_max_tokens")
        ollama_num_ctx = _workspace_config_override(tenant_id, "ollama_num_ctx")
        adjuster_service = (
            get_context_adjuster_service(
                generalize_model_name=generalizer_model,
                generalize_system_prompt=generalizer_prompt,
                rewrite_max_tokens=rewrite_max_tokens,
                num_ctx=ollama_num_ctx,
            )
            if (generalizer_model or generalizer_prompt or rewrite_max_tokens or ollama_num_ctx)
            else get_context_adjuster_service()
        )
        generalized = await adjuster_service.generalize(answer)
        # Re-read right before the upsert: generalize() takes seconds, which is
        # the window an edit most likely lands in. Same pair as the two
        # background store paths.
        if is_human_authored(memory, doc_id):
            logger.info(
                "feedback_escalation cache_store status=skipped reason=human_authored_race "
                "namespace=%s doc_id=%s",
                cache_namespace,
                doc_id,
            )
            return
        memory.store_interaction(
            clean_query,
            generalized,
            original_query,
            tenant_id,
        )
        logger.info(
            "feedback_escalation cache_store status=stored namespace=%s doc_id=%s",
            cache_namespace,
            doc_id,
        )
    except Exception:
        logger.exception(
            "feedback_escalation cache_store status=failed namespace=%s doc_id=%s",
            cache_namespace,
            doc_id,
        )


def _schedule_escalation_cache_store(
    *,
    clean_query: str,
    answer: str,
    original_query: str,
    tenant_id: str,
    cache_namespace: str,
) -> None:
    asyncio.create_task(
        _store_escalation_cache_entry(
            clean_query=clean_query,
            answer=answer,
            original_query=original_query,
            tenant_id=tenant_id,
            cache_namespace=cache_namespace,
        )
    )


async def _cache_response_id_for_escalation(
    *,
    interaction,
    query: str,
    history: list[dict],
    answer: str,
    truncated: bool,
) -> str | None:
    # Same rule the miss path applies to its own generation, enforced here
    # because this is the one place either escalation branch stores: a cut-off
    # answer never enters the cache, since a stored truncation is what every
    # later match is served - labelled finish_reason="stop", because a hit
    # carries no truncation signal - and it never self-heals. The escalated
    # answer still reaches the user who asked for it; only the store is skipped.
    # Required rather than defaulted so a future caller has to say which it has.
    if truncated:
        logger.warning(
            "feedback_escalation cache_store status=skipped reason=truncated "
            "interaction_id=%s",
            interaction.interaction_id,
        )
        return None

    # Same rule as the miss path (openai_compat.py) - an empty answer (e.g. a
    # safety-blocked provider response normalized to finish_reason="stop") is
    # not an answer, and caching it means every later match is served silence.
    if not answer.strip():
        logger.warning(
            "feedback_escalation cache_store status=skipped reason=empty_answer "
            "interaction_id=%s",
            interaction.interaction_id,
        )
        return None

    # The re-answer above was generated from message.history alone, blind to
    # whatever image/file the original cached answer was anchored to (the
    # client never re-sends attachment bytes on a feedback replay). Storing it
    # as an ungated text entry is exactly the poisoning the image/file gates
    # exist to prevent - refuse the store rather than trust a blind answer.
    if await _parent_is_attachment_anchored(interaction):
        logger.warning(
            "feedback_escalation cache_store status=skipped reason=attachment_anchored "
            "interaction_id=%s",
            interaction.interaction_id,
        )
        return None

    try:
        enricher_model = _workspace_config_override(interaction.workspace_slug, "enricher_model")
        enricher_prompt = _workspace_config_override(interaction.workspace_slug, "enricher_system_prompt")
        enricher_num_ctx = _workspace_config_override(interaction.workspace_slug, "ollama_num_ctx")
        enricher_service = (
            get_context_enricher_service(
                model_name=enricher_model, system_prompt=enricher_prompt, num_ctx=enricher_num_ctx
            )
            if (enricher_model or enricher_prompt or enricher_num_ctx)
            else get_context_enricher_service()
        )
        enriched = await enricher_service.enrich(query, history)
    except Exception:
        logger.exception("Feedback escalation cache enrich failed")
        enriched = query

    try:
        normalizer_model = _workspace_config_override(interaction.workspace_slug, "normalizer_model")
        normalizer_prompt = _workspace_config_override(interaction.workspace_slug, "normalizer_system_prompt")
        normalizer_num_ctx = _workspace_config_override(interaction.workspace_slug, "ollama_num_ctx")
        normalizer_service = (
            get_normalizer_service(
                model_name=normalizer_model, system_prompt=normalizer_prompt, num_ctx=normalizer_num_ctx
            )
            if (normalizer_model or normalizer_prompt or normalizer_num_ctx)
            else get_normalizer_service()
        )
        clean_query = await normalizer_service.normalize(enriched)
    except Exception:
        logger.exception("Feedback escalation cache normalize failed")
        clean_query = enriched

    try:
        should_cache, reason = cache_filter.should_cache(enriched, clean_query)
    except Exception:
        logger.exception("Feedback escalation cache filter failed")
        should_cache = False
        reason = "filter failed"

    if not should_cache:
        logger.info("feedback_escalation cache_store status=skipped reason=%s", reason)
        return None

    _schedule_escalation_cache_store(
        clean_query=clean_query,
        answer=answer,
        original_query=query,
        tenant_id=interaction.workspace_slug,
        cache_namespace=interaction.cache_namespace,
    )
    return f"{interaction.cache_namespace}:{_doc_id(clean_query)}"


async def _log_escalation_usage(
    *,
    interaction,
    child_interaction_id: str,
    latency_ms: int,
    model_used: str | None,
    served_tier: str,
    external_provider_used: bool,
    finish_reason: str,
) -> None:
    try:
        await request_logger.log(
            interaction.workspace_slug,
            interaction.department,
            latency_ms,
            False,
            "hard" if served_tier == "external" else "easy",
            model_used,
            response_id=None,
            source="feedback_escalation",
            interaction_id=child_interaction_id,
            parent_interaction_id=interaction.interaction_id,
            served_tier=served_tier,
            external_provider_used=external_provider_used,
            finish_reason=finish_reason,
        )
    except Exception:
        logger.exception("Failed to log feedback escalation usage interaction_id=%s", interaction.interaction_id)


async def escalate(*, interaction, messages: list[dict]) -> EscalationResult:
    if interaction.served_tier == "external":
        return EscalationResult(escalation_status="no_further_escalation")

    query, history, system_prompt = extract_pipeline_inputs(messages)
    if not query:
        return EscalationResult(escalation_status="provider_error")

    if interaction.served_tier == "cache":
        return await _escalate_to_local(
            interaction=interaction,
            messages=messages,
            query=query,
            history=history,
            system_prompt=system_prompt,
        )
    if interaction.served_tier == "local":
        return await _escalate_to_external(
            interaction=interaction,
            messages=messages,
            query=query,
            history=history,
            system_prompt=system_prompt,
        )
    return EscalationResult(escalation_status="provider_error")


async def _escalate_to_local(
    *,
    interaction,
    messages: list[dict],
    query: str,
    history: list[dict],
    system_prompt: str | None,
) -> EscalationResult:
    local_model = _workspace_config_override(interaction.workspace_slug, "local_model")
    local_prompt = _workspace_config_override(interaction.workspace_slug, "local_model_system_prompt")
    router_service = (
        get_llm_router_service(model_name=local_model, default_system_prompt=local_prompt)
        if (local_model or local_prompt)
        else get_llm_router_service()
    )
    try:
        answer, latency, done_reason = await asyncio.wait_for(
            router_service.generate_local_response(
                query,
                history=history,
                max_tokens=_effective_default_max_tokens(interaction.workspace_slug),
                # None (client sent no system prompt of its own) falls
                # through to router_service.default_system_prompt - the
                # workspace's local_model_system_prompt override when set,
                # otherwise the hardcoded literal. Hardcoding the literal
                # here too would silently shadow that override.
                system_prompt=system_prompt,
            ),
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning("Local feedback escalation timed out interaction_id=%s", interaction.interaction_id)
        return EscalationResult(escalation_status="timeout")
    except Exception:
        logger.exception("Local feedback escalation failed interaction_id=%s", interaction.interaction_id)
        return EscalationResult(escalation_status="provider_error")

    child = await response_registry.register(
        response_id=await _cache_response_id_for_escalation(
            interaction=interaction,
            query=query,
            history=history,
            answer=answer,
            truncated=done_reason == "length",
        ),
        workspace_id=interaction.workspace_id,
        workspace_slug=interaction.workspace_slug,
        department=interaction.department,
        cache_namespace=interaction.cache_namespace,
        served_tier="local",
        messages=messages,
    )
    await _log_escalation_usage(
        interaction=interaction,
        child_interaction_id=child.interaction_id,
        latency_ms=int(latency),
        model_used="local",
        served_tier="local",
        external_provider_used=False,
        finish_reason="length" if done_reason == "length" else "stop",
    )
    return EscalationResult(
        escalated_response=EscalatedResponse(
            content=answer,
            tier="local",
            interaction_id=child.interaction_id,
            response_id=child.response_id,
        ),
        escalation_status="answered",
    )


async def _escalate_to_external(
    *,
    interaction,
    messages: list[dict],
    query: str,
    history: list[dict],
    system_prompt: str | None,
) -> EscalationResult:
    if interaction.workspace_id is None:
        return EscalationResult(escalation_status="no_credential")

    try:
        config = llm_config_service.read_for_workspace(interaction.workspace_slug)
        if not config.external_model:
            raise ValueError("workspace has no external model configured")
        provider = config.external_provider or llm_config_service.resolve_provider_for_model(
            config.external_model
        )
        if provider is None:
            raise ValueError(
                f"external model '{config.external_model}' is not mapped to a supported provider"
            )
        with get_session() as session:
            api_key = CredentialService().get_decrypted_key(session, interaction.workspace_id, provider)
    except ValueError:
        logger.warning("External escalation credential/config unavailable interaction_id=%s", interaction.interaction_id)
        return EscalationResult(escalation_status="no_credential")
    except Exception:
        logger.exception("External escalation setup failed interaction_id=%s", interaction.interaction_id)
        return EscalationResult(escalation_status="provider_error")

    if api_key is None:
        return EscalationResult(escalation_status="no_credential")

    request = ExternalLLMRequest(
        query=query,
        history=history,
        model=config.external_model,
        max_tokens=config.default_max_tokens,
        system_prompt=system_prompt
        or "You are a helpful assistant. Answer the user's query concisely and accurately.",
    )
    try:
        response = await asyncio.wait_for(
            ExternalLLMService().generate_response(request, provider=provider, api_key=api_key),
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
    except (TimeoutError, ExternalLLMTimeoutError):
        logger.warning("External feedback escalation timed out interaction_id=%s", interaction.interaction_id)
        return EscalationResult(escalation_status="timeout")
    except ExternalLLMAuthError:
        return EscalationResult(escalation_status="no_credential")
    except ExternalLLMError:
        logger.exception("External feedback escalation failed interaction_id=%s", interaction.interaction_id)
        return EscalationResult(escalation_status="provider_error")
    except Exception:
        logger.exception("External feedback escalation failed interaction_id=%s", interaction.interaction_id)
        return EscalationResult(escalation_status="provider_error")

    child = await response_registry.register(
        response_id=await _cache_response_id_for_escalation(
            interaction=interaction,
            query=query,
            history=history,
            answer=response.text,
            truncated=response.finish_reason == "length",
        ),
        workspace_id=interaction.workspace_id,
        workspace_slug=interaction.workspace_slug,
        department=interaction.department,
        cache_namespace=interaction.cache_namespace,
        served_tier="external",
        messages=messages,
    )
    await _log_escalation_usage(
        interaction=interaction,
        child_interaction_id=child.interaction_id,
        latency_ms=int(response.latency_ms),
        model_used=response.model_used,
        served_tier="external",
        external_provider_used=True,
        finish_reason=response.finish_reason,
    )
    return EscalationResult(
        escalated_response=EscalatedResponse(
            content=response.text,
            tier="external",
            interaction_id=child.interaction_id,
            response_id=child.response_id,
        ),
        escalation_status="answered",
    )
