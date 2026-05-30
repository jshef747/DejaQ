from __future__ import annotations

import logging

from app import config
from app.services.context_adjuster import ContextAdjusterService
from app.services.context_enricher import ContextEnricherService
from app.services.llm_router import LLMRouterService
from app.services.model_backends import ModelBackend, OllamaBackend
from app.services.normalizer import NormalizerService
from app.services.validator import ValidatorService

logger = logging.getLogger("dejaq.services.service_factory")

_backend: ModelBackend | None = None
_service_pool: dict[str, object] = {}


def _get_backend() -> ModelBackend:
    """Return the shared Ollama backend (local or remote per DEJAQ_OLLAMA_URL)."""
    global _backend
    if _backend is None:
        _backend = OllamaBackend(
            base_url=config.OLLAMA_URL,
            timeout_seconds=config.OLLAMA_TIMEOUT_SECONDS,
        )
        logger.info(
            "Initialized model backend: ollama url=%s timeout=%.1fs",
            config.OLLAMA_URL,
            config.OLLAMA_TIMEOUT_SECONDS,
        )
    return _backend


def _service_key(role: str, *parts: str) -> str:
    return ":".join((role, *parts))


def get_normalizer_service(model_name: str | None = None) -> NormalizerService:
    resolved_model_name = model_name or config.NORMALIZER_MODEL_NAME
    service_key = _service_key("normalizer", resolved_model_name)
    service = _service_pool.get(service_key)
    if service is None:
        service = NormalizerService(
            backend=_get_backend(),
            model_name=resolved_model_name,
        )
        _service_pool[service_key] = service
        logger.info("Configured service role=normalizer model=%s", resolved_model_name)
    return service  # type: ignore[return-value]


def get_context_enricher_service(model_name: str | None = None) -> ContextEnricherService:
    resolved_model_name = model_name or config.ENRICHER_MODEL_NAME
    service_key = _service_key("enricher", resolved_model_name)
    service = _service_pool.get(service_key)
    if service is None:
        service = ContextEnricherService(
            backend=_get_backend(),
            model_name=resolved_model_name,
        )
        _service_pool[service_key] = service
        logger.info("Configured service role=enricher model=%s", resolved_model_name)
    return service  # type: ignore[return-value]


def get_context_adjuster_service(
    adjust_model_name: str | None = None,
    generalize_model_name: str | None = None,
) -> ContextAdjusterService:
    resolved_adjust_model_name = adjust_model_name or config.CONTEXT_ADJUSTER_MODEL_NAME
    resolved_generalize_model_name = generalize_model_name or config.GENERALIZER_MODEL_NAME
    service_key = _service_key(
        "adjuster",
        resolved_adjust_model_name,
        resolved_generalize_model_name,
    )
    service = _service_pool.get(service_key)
    if service is None:
        service = ContextAdjusterService(
            adjust_backend=_get_backend(),
            adjust_model_name=resolved_adjust_model_name,
            generalize_backend=_get_backend(),
            generalize_model_name=resolved_generalize_model_name,
        )
        _service_pool[service_key] = service
        logger.info(
            "Configured service role=context_adjuster adjust_model=%s generalize_model=%s",
            resolved_adjust_model_name,
            resolved_generalize_model_name,
        )
    return service  # type: ignore[return-value]


def get_validator_service(model_name: str | None = None) -> ValidatorService:
    resolved_model_name = model_name or config.VALIDATOR_MODEL_NAME
    service_key = _service_key("validator", resolved_model_name)
    service = _service_pool.get(service_key)
    if service is None:
        service = ValidatorService(
            backend=_get_backend(),
            model_name=resolved_model_name,
        )
        _service_pool[service_key] = service
        logger.info("Configured service role=validator model=%s", resolved_model_name)
    return service  # type: ignore[return-value]


def get_llm_router_service(model_name: str | None = None) -> LLMRouterService:
    resolved_model_name = model_name or config.LOCAL_LLM_MODEL_NAME
    service_key = _service_key("llm_router", resolved_model_name)
    service = _service_pool.get(service_key)
    if service is None:
        service = LLMRouterService(
            backend=_get_backend(),
            model_name=resolved_model_name,
        )
        _service_pool[service_key] = service
        logger.info("Configured service role=local_llm model=%s", resolved_model_name)
    return service  # type: ignore[return-value]
