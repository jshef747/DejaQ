from __future__ import annotations

import logging

from app import config
from app.services.context_adjuster import ContextAdjusterService
from app.services.context_enricher import ContextEnricherService
from app.services.llm_router import LLMRouterService
from app.services.model_backends import InProcessBackend, ModelBackend, OllamaBackend
from app.services.normalizer import NormalizerService

logger = logging.getLogger("dejaq.services.service_factory")

_backend_pool: dict[str, ModelBackend] = {}
_service_pool: dict[str, object] = {}


def _get_backend(backend_name: str) -> ModelBackend:
    backend = _backend_pool.get(backend_name)
    if backend is not None:
        return backend

    if backend_name == "in_process":
        backend = InProcessBackend()
        logger.info("Initialized model backend: in_process")
    elif backend_name == "ollama":
        backend = OllamaBackend(
            base_url=config.OLLAMA_URL,
            timeout_seconds=config.OLLAMA_TIMEOUT_SECONDS,
        )
        logger.info(
            "Initialized model backend: ollama url=%s timeout=%.1fs",
            config.OLLAMA_URL,
            config.OLLAMA_TIMEOUT_SECONDS,
        )
    else:
        raise ValueError(f"Unsupported backend: {backend_name}")

    _backend_pool[backend_name] = backend
    return backend


def get_normalizer_service() -> NormalizerService:
    service = _service_pool.get("normalizer")
    if service is None:
        service = NormalizerService(
            backend=_get_backend(config.NORMALIZER_BACKEND),
            model_name=config.NORMALIZER_MODEL_NAME,
        )
        _service_pool["normalizer"] = service
        logger.info(
            "Configured service role=normalizer backend=%s model=%s",
            config.NORMALIZER_BACKEND,
            config.NORMALIZER_MODEL_NAME,
        )
    return service  # type: ignore[return-value]


def get_context_enricher_service() -> ContextEnricherService:
    service = _service_pool.get("enricher")
    if service is None:
        service = ContextEnricherService(
            backend=_get_backend(config.ENRICHER_BACKEND),
            model_name=config.ENRICHER_MODEL_NAME,
        )
        _service_pool["enricher"] = service
        logger.info(
            "Configured service role=enricher backend=%s model=%s",
            config.ENRICHER_BACKEND,
            config.ENRICHER_MODEL_NAME,
        )
    return service  # type: ignore[return-value]


def get_context_adjuster_service() -> ContextAdjusterService:
    service = _service_pool.get("adjuster")
    if service is None:
        service = ContextAdjusterService(
            adjust_backend=_get_backend(config.CONTEXT_ADJUSTER_BACKEND),
            adjust_model_name=config.CONTEXT_ADJUSTER_MODEL_NAME,
            generalize_backend=_get_backend(config.GENERALIZER_BACKEND),
            generalize_model_name=config.GENERALIZER_MODEL_NAME,
        )
        _service_pool["adjuster"] = service
        logger.info(
            "Configured service role=context_adjuster backend=%s model=%s",
            config.CONTEXT_ADJUSTER_BACKEND,
            config.CONTEXT_ADJUSTER_MODEL_NAME,
        )
        logger.info(
            "Configured service role=generalizer backend=%s model=%s",
            config.GENERALIZER_BACKEND,
            config.GENERALIZER_MODEL_NAME,
        )
    return service  # type: ignore[return-value]


def get_llm_router_service() -> LLMRouterService:
    service = _service_pool.get("llm_router")
    if service is None:
        service = LLMRouterService(
            backend=_get_backend(config.LOCAL_LLM_BACKEND),
            model_name=config.LOCAL_LLM_MODEL_NAME,
        )
        _service_pool["llm_router"] = service
        logger.info(
            "Configured service role=local_llm backend=%s model=%s",
            config.LOCAL_LLM_BACKEND,
            config.LOCAL_LLM_MODEL_NAME,
        )
    return service  # type: ignore[return-value]
