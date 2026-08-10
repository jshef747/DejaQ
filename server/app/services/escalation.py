from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Literal

from pydantic import BaseModel

from app.config import DEFAULT_MAX_TOKENS, OLLAMA_TIMEOUT_SECONDS
from app.db.session import get_session
from app.schemas.chat import ExternalLLMRequest
from app.schemas.feedback import EscalatedResponse
from app.services import cache_filter, llm_config_service, pipeline_config_cache
from app.services.chat_messages import extract_pipeline_inputs
from app.services.credential_service import CredentialService
from app.services.external_llm import ExternalLLMService
from app.services.memory_chromaDB import get_memory_service
from app.services.provider_inference import provider_for_model
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


def _workspace_model_override(workspace_slug: str, field: str) -> str | None:
    """The workspace's override for `field` (e.g. "local_model",
    "generalizer_model", "enricher_model", "normalizer_model"), or None when
    there isn't one - including when the workspace can't be resolved at all.
    None lets callers make the exact same no-override get_*_service() call
    this module always made before per-workspace pipeline config existed.
    """
    try:
        config = pipeline_config_cache.get_effective_config(workspace_slug)
    except llm_config_service.WorkspaceNotFound:
        return None
    if field not in config.overrides:
        return None
    return getattr(config, field)


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
        generalizer_model = _workspace_model_override(tenant_id, "generalizer_model")
        adjuster_service = (
            get_context_adjuster_service(generalize_model_name=generalizer_model)
            if generalizer_model
            else get_context_adjuster_service()
        )
        generalized = await adjuster_service.generalize(answer)
        get_memory_service(cache_namespace).store_interaction(
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
        enricher_model = _workspace_model_override(interaction.workspace_slug, "enricher_model")
        enricher_service = (
            get_context_enricher_service(model_name=enricher_model)
            if enricher_model
            else get_context_enricher_service()
        )
        enriched = await enricher_service.enrich(query, history)
    except Exception:
        logger.exception("Feedback escalation cache enrich failed")
        enriched = query

    try:
        normalizer_model = _workspace_model_override(interaction.workspace_slug, "normalizer_model")
        normalizer_service = (
            get_normalizer_service(model_name=normalizer_model)
            if normalizer_model
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
    local_model = _workspace_model_override(interaction.workspace_slug, "local_model")
    router_service = (
        get_llm_router_service(model_name=local_model) if local_model else get_llm_router_service()
    )
    try:
        answer, latency, done_reason = await asyncio.wait_for(
            router_service.generate_local_response(
                query,
                history=history,
                max_tokens=DEFAULT_MAX_TOKENS,
                system_prompt=system_prompt
                or "You are a helpful assistant. Answer the user's query concisely and accurately.",
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
        provider = provider_for_model(config.external_model)
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
        max_tokens=DEFAULT_MAX_TOKENS,
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
