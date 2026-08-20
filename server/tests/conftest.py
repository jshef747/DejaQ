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


class StreamingLocalRouterMixin:
    """Gives a stub local router the streaming call the pipeline uses.

    Derived from the stub's OWN generate_local_response rather than written
    out a second time, so a double cannot answer one thing buffered and
    another thing streamed - which is exactly how a streaming regression
    would hide from a suite full of non-streaming stubs.
    """

    async def stream_local_response(self, query, history=None, max_tokens=1024, system_prompt=None, images=None):
        from app.services.model_backends import CompletionChunk

        kwargs = {"history": history, "max_tokens": max_tokens, "system_prompt": system_prompt}
        if images is not None:
            kwargs["images"] = images
        text, _latency, done_reason = await self.generate_local_response(query, **kwargs)
        if text:
            yield CompletionChunk(text=text)
        yield CompletionChunk(done_reason=done_reason)


def _reset_backend() -> None:
    _sf._backend = None
    _service_pool.clear()


def _org_engine(db_path: Path):
    """SQLite engine for an org DB, with the same FK pragma app.db.base sets."""
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


@pytest.fixture(scope="session", autouse=True)
def _ensure_default_org_schema(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Bind the DEFAULT SessionLocal to a throwaway org DB for the whole run.

    Most tests hit the real app through TestClient without asking for
    `isolated_org_db`, so they read whatever `SessionLocal` is bound to. That
    default is `server/dejaq.db` - the developer's own DB - which is gitignored
    and therefore absent (or an empty 0-byte file) in a fresh clone or
    worktree, so the first DB read in the request pipeline raises `no such
    table: workspaces` and ~39 tests fail for setup reasons alone.

    Creating the tables in that file instead would fix the missing-table error
    but leave the file schema-current and alembic-unstamped, so the next
    `alembic upgrade head` (start.sh) replays from base onto tables that
    already exist and aborts; stamping it head afterwards would be worse still
    on a developer's real DB, since `create_all` skips existing tables and so
    never applies a pending column migration the stamp would then declare
    done. A per-run temp DB has neither problem, and keeps a test run from
    writing to a real deployment DB at all.
    """
    engine = _org_engine(tmp_path_factory.mktemp("org-db") / "dejaq.db")
    SessionLocal.configure(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        engine.dispose()


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
    engine = _org_engine(db_path)

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


@pytest.fixture(autouse=True)
def _reset_pipeline_config_cache():
    """Clear the in-process per-workspace pipeline config cache around every test.

    pipeline_config_cache._CACHE is a module-level singleton (TTL + db-mtime
    gated, services/pipeline_config_cache.py) that outlives any single test's
    monkeypatch of llm_config_service.read_for_workspace. Without this, a test
    that stubs read_for_workspace to a minimal object can leave that stub
    cached under a workspace slug (e.g. "acme"), which a later, unrelated test
    reusing the same slug then reads back - even though the later test never
    patched anything itself. Reset on both sides of the test so pollution
    can't leak forward from setup either.
    """
    from app.services import pipeline_config_cache
    pipeline_config_cache.invalidate()
    yield
    pipeline_config_cache.invalidate()


@pytest.fixture
def authed_admin_client():
    """TestClient for the main app with management auth pre-satisfied as system actor."""
    from app.main import app
    from app.dependencies.admin_auth import require_management_auth

    ctx = ManagementAuthContext.local_dev()
    app.dependency_overrides[require_management_auth] = lambda: ctx
    try:
        yield TestClient(app), {"Authorization": "Bearer test-system-token"}
    finally:
        app.dependency_overrides.pop(require_management_auth, None)


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
