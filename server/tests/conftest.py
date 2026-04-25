from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event

from app.db.base import Base, SessionLocal
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


@pytest.fixture
def deterministic_utc_ts() -> datetime:
    return datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def isolated_org_db(tmp_path: Path) -> Iterator[Path]:
    """Use a per-test SQLite org DB and keep SQLAlchemy FK behavior enabled."""
    import app.db.models  # noqa: F401 - register metadata models

    db_path = tmp_path / "dejaq-test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    previous_bind = SessionLocal.kw["bind"]
    SessionLocal.configure(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield db_path
    finally:
        SessionLocal.configure(bind=previous_bind)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def isolated_stats_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "dejaq-stats-test.db"
    monkeypatch.setenv("DEJAQ_STATS_DB", str(db_path))
    monkeypatch.setattr("app.config.STATS_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr("app.services.request_logger.STATS_DB_PATH", str(db_path), raising=False)
    return db_path


@pytest.fixture
def admin_token_env(monkeypatch: pytest.MonkeyPatch):
    def _set(token: str | None) -> None:
        if token is None:
            monkeypatch.delenv("DEJAQ_ADMIN_TOKEN", raising=False)
        else:
            monkeypatch.setenv("DEJAQ_ADMIN_TOKEN", token)

    return _set


@pytest.fixture
def mock_feedback_cache(monkeypatch: pytest.MonkeyPatch):
    class _Cache:
        def __init__(self) -> None:
            self.scores: dict[str, float] = {}
            self.deleted: set[str] = set()

        def set_score(self, response_id: str, score: float) -> None:
            self.scores[response_id] = score

        def delete(self, response_id: str) -> None:
            self.deleted.add(response_id)

    cache = _Cache()
    return cache
