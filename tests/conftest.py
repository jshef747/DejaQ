import pytest

from app.services.cache_filter import should_cache
from app.services.conversation_store import ConversationStore
from app.services.memory_chromaDB import MemoryService


# ── No-model fixtures (function-scoped for isolation) ──

@pytest.fixture
def fresh_conversation_store():
    return ConversationStore()


@pytest.fixture
def memory_service(tmp_path):
    return MemoryService(
        collection_name="test_collection",
        persist_directory=str(tmp_path / "chroma_test"),
    )


# ── Model-backed fixtures (session-scoped — load once) ──

@pytest.fixture(scope="session")
def normalizer_service():
    from app.services.normalizer import NormalizerService
    return NormalizerService()


@pytest.fixture(scope="session")
def context_enricher_service():
    from app.services.context_enricher import ContextEnricherService
    return ContextEnricherService()


@pytest.fixture(scope="session")
def context_adjuster_service():
    from app.services.context_adjuster import ContextAdjusterService
    return ContextAdjusterService()


@pytest.fixture(scope="session")
def llm_router_service():
    from app.services.llm_router import LLMRouterService
    return LLMRouterService()


@pytest.fixture(scope="session")
def classifier_service():
    from app.services.classifier import ClassifierService
    return ClassifierService()
