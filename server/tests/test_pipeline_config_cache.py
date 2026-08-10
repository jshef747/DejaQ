import time

import pytest


def _create_workspace(name: str = "Acme") -> None:
    from app.db import workspace_repo
    from app.db.session import get_session

    with get_session() as session:
        workspace_repo.create_workspace(session, name)


def test_picks_up_a_db_change_before_ttl_via_mtime(isolated_org_db, monkeypatch):
    """Mirrors test_key_cache_invalidation.py's out-of-process pickup test:
    the Celery worker is a separate process from the FastAPI request that
    dispatched it, so only the DB file's own mtime (not an in-process
    invalidate() call) lets it see a dashboard edit without waiting out the
    TTL - see services/pipeline_config_cache.py."""
    from app.config import GENERALIZER_MODEL_NAME
    from app.services import llm_config_service
    from app.services.llm_config_service import update_for_workspace
    from app.services.model_backends import MODEL_RUNTIME_SPECS
    from app.services.pipeline_config_cache import _PipelineConfigCache

    monkeypatch.setattr(
        llm_config_service.ollama_catalog, "list_available_models", lambda force_refresh=False: ["gemma4:e4b"]
    )
    _create_workspace()

    # Long TTL: any pickup must come from the mtime signal, not TTL expiry.
    cache = _PipelineConfigCache(ttl_seconds=3600)
    assert cache.get("acme").generalizer_model == MODEL_RUNTIME_SPECS[GENERALIZER_MODEL_NAME].ollama_model

    time.sleep(0.01)  # ensure the filesystem mtime actually advances
    update_for_workspace("acme", {"generalizer_model": "gemma4:e4b"}, {"generalizer_model"})

    assert cache.get("acme").generalizer_model == "gemma4:e4b"


def test_invalidate_forces_an_immediate_reread(isolated_org_db, monkeypatch):
    from app.services import llm_config_service
    from app.services.llm_config_service import update_for_workspace
    from app.services.pipeline_config_cache import _PipelineConfigCache

    monkeypatch.setattr(
        llm_config_service.ollama_catalog, "list_available_models", lambda force_refresh=False: ["gemma4:e4b"]
    )
    _create_workspace()

    cache = _PipelineConfigCache(ttl_seconds=3600)
    assert cache.get("acme").is_default is True

    update_for_workspace("acme", {"generalizer_model": "gemma4:e4b"}, {"generalizer_model"})
    cache.invalidate("acme")

    assert cache.get("acme").generalizer_model == "gemma4:e4b"


def test_unknown_workspace_is_never_cached(isolated_org_db):
    """A WorkspaceNotFound miss must not poison the cache - a workspace
    created moments later has to resolve on the very next call."""
    from app.services.llm_config_service import WorkspaceNotFound
    from app.services.pipeline_config_cache import _PipelineConfigCache

    cache = _PipelineConfigCache(ttl_seconds=3600)
    with pytest.raises(WorkspaceNotFound):
        cache.get("acme")

    _create_workspace()

    assert cache.get("acme").is_default is True
