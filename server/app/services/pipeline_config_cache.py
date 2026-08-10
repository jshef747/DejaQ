"""In-process TTL cache of each workspace's effective pipeline LLM config.

Same shape as middleware/api_key.py's _KeyCache: TTL-refreshed, plus early
invalidation on the backing SQLite file's mtime, so a dashboard edit made in
the FastAPI process is visible to the Celery worker process (a separate
process running generalize_and_store_task) and to escalation.py's re-answer
path without a restart and without waiting out the full TTL once the file
has actually changed. invalidate() additionally makes the editing process's
own next read instant, rather than waiting on the TTL/mtime check at all.
"""
import logging
import time

from app.config import KEY_CACHE_TTL
from app.services import llm_config_service
from app.utils.db_freshness import db_mtime

logger = logging.getLogger("dejaq.services.pipeline_config_cache")


class _PipelineConfigCache:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        # workspace_slug -> (loaded_at, db_mtime_at_load, LlmConfigResult)
        self._entries: dict[str, tuple[float, float, "llm_config_service.LlmConfigResult"]] = {}

    def _is_stale(self, workspace_slug: str) -> bool:
        entry = self._entries.get(workspace_slug)
        if entry is None:
            return True
        loaded_at, mtime_at_load, _ = entry
        if (time.monotonic() - loaded_at) >= self._ttl:
            return True
        return db_mtime() > mtime_at_load

    def get(self, workspace_slug: str) -> "llm_config_service.LlmConfigResult":
        if self._is_stale(workspace_slug):
            result = llm_config_service.read_for_workspace(workspace_slug)
            self._entries[workspace_slug] = (time.monotonic(), db_mtime(), result)
        return self._entries[workspace_slug][2]

    def invalidate(self, workspace_slug: str | None = None) -> None:
        if workspace_slug is None:
            self._entries.clear()
        else:
            self._entries.pop(workspace_slug, None)


_CACHE = _PipelineConfigCache(ttl_seconds=KEY_CACHE_TTL)


def get_effective_config(workspace_slug: str) -> "llm_config_service.LlmConfigResult":
    """Return the effective pipeline config for a workspace.

    Raises llm_config_service.WorkspaceNotFound for an unknown slug - never
    cached, so a workspace created moments ago resolves on the next call.
    """
    return _CACHE.get(workspace_slug)


def invalidate(workspace_slug: str | None = None) -> None:
    _CACHE.invalidate(workspace_slug)
