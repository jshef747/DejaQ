import pytest

from app.services.cache_filter import should_cache
from app.services.memory_chromaDB import MemoryService
from app.services.service_factory import (
    _backend_pool,
    _service_pool,
    get_context_adjuster_service,
    get_context_enricher_service,
    get_llm_router_service,
    get_normalizer_service,
)


# ── No-model fixtures (function-scoped for isolation) ──

@pytest.fixture
def memory_service():
    return MemoryService(collection_name="test_collection")


# ── Model-backed fixtures (session-scoped — load once) ──

@pytest.fixture(scope="session")
def normalizer_service():
    _backend_pool.clear()
    _service_pool.clear()
    return get_normalizer_service()


@pytest.fixture(scope="session")
def context_enricher_service():
    _backend_pool.clear()
    _service_pool.clear()
    return get_context_enricher_service()


@pytest.fixture(scope="session")
def context_adjuster_service():
    _backend_pool.clear()
    _service_pool.clear()
    return get_context_adjuster_service()


@pytest.fixture(scope="session")
def llm_router_service():
    _backend_pool.clear()
    _service_pool.clear()
    return get_llm_router_service()


@pytest.fixture(scope="session")
def classifier_service():
    from app.services.classifier import ClassifierService
    return ClassifierService()
