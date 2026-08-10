from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event

from app.db.base import Base, SessionLocal
from app.dependencies.management_auth import ManagementAuthContext
from app.services.cache_filter import should_cache
from app.services.memory_chromaDB import MemoryService
import app.services.service_factory as _sf
from app.services.service_factory import (
    _service_pool,
    get_context_adjuster_service,
    get_context_enricher_service,
    get_llm_router_service,
    get_normalizer_service,
)


def _reset_backend() -> None:
    _sf._backend = None
    _service_pool.clear()


# ── No-model fixtures (function-scoped for isolation) ──

@pytest.fixture
def memory_service():
    return MemoryService(collection_name="test_collection")


# ── Model-backed fixtures (session-scoped — load once) ──

@pytest.fixture(scope="session")
def normalizer_service():
    _reset_backend()
    return get_normalizer_service()


@pytest.fixture(scope="session")
def context_enricher_service():
    _reset_backend()
    return get_context_enricher_service()


@pytest.fixture(scope="session")
def context_adjuster_service():
    _reset_backend()
    return get_context_adjuster_service()


@pytest.fixture(scope="session")
def llm_router_service():
    _reset_backend()
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



@pytest.fixture(autouse=True)
def _disable_admin_loopback(monkeypatch):
    """Disable the AdminLoopbackMiddleware for all tests.

    TestClient uses a non-loopback transport peer ('testclient'), which the
    middleware rejects with 403. Tests need direct admin API access, so we
    disable the loopback gate for the duration of each test.
    """
    import app.middleware.admin_loopback as _alb
    monkeypatch.setattr(_alb, "ADMIN_LOOPBACK_ONLY", False)


@pytest.fixture
def authed_admin_client():
    """TestClient for the main app with management auth pre-satisfied as system actor."""
    from app.main import app
    from app.dependencies.admin_auth import require_management_auth

    ctx = ManagementAuthContext.system()
    app.dependency_overrides[require_management_auth] = lambda: ctx
    try:
        yield TestClient(app), {"Authorization": "Bearer test-system-token"}
    finally:
        app.dependency_overrides.pop(require_management_auth, None)


@pytest.fixture
def scoped_admin_client():
    """
    Factory fixture that yields a callable: build_client(accessible_workspaces) -> (TestClient, headers).

    Pass a list of WorkspaceRef objects to build a user actor scoped to exactly those workspaces.
    Used to test that user actors are denied access to workspaces they are not members of.
    """
    from app.main import app
    from app.dependencies.admin_auth import require_management_auth
    from app.dependencies.management_auth import WorkspaceRef

    _override_key = require_management_auth

    def build_client(accessible_workspaces: list[WorkspaceRef]):
        ctx = ManagementAuthContext(
            actor_type="user",
            local_user_id=1,
            supabase_user_id="test-supabase-uid",
            email="test@example.com",
            accessible_workspaces=accessible_workspaces,
        )
        app.dependency_overrides[_override_key] = lambda: ctx
        return TestClient(app), {"Authorization": "Bearer test-user-token"}

    try:
        yield build_client
    finally:
        app.dependency_overrides.pop(_override_key, None)


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
