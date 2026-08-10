"""Live discovery of Ollama models actually installed on the configured host.

Backs the per-workspace pipeline model pickers (dashboard Pipeline page): the
captain's decision is that any locally-installed Ollama tag is selectable,
not just tags already registered in MODEL_RUNTIME_SPECS, so installing a
model must be enough to make it selectable with no code change. Both the
discovery GET and the admin PUT validation (llm_config_service) call
list_available_models() so a value can never be accepted that Ollama itself
does not report as installed at write time.
"""
from __future__ import annotations

import logging
import time

import httpx

from app.config import OLLAMA_CATALOG_CACHE_TTL_SECONDS, OLLAMA_TIMEOUT_SECONDS, OLLAMA_URL

logger = logging.getLogger("dejaq.services.ollama_catalog")


class OllamaUnreachableError(Exception):
    """Ollama's /api/tags could not be reached or returned a bad response."""


def _fetch_tags() -> list[str]:
    try:
        response = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=OLLAMA_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise OllamaUnreachableError(f"Ollama is unreachable at {OLLAMA_URL}: {exc}") from exc
    except ValueError as exc:
        raise OllamaUnreachableError(f"Ollama at {OLLAMA_URL} returned an unparseable response: {exc}") from exc
    models = data.get("models")
    if not isinstance(models, list):
        raise OllamaUnreachableError(f"Ollama at {OLLAMA_URL} returned an unexpected /api/tags shape")
    return sorted(m["name"] for m in models if isinstance(m, dict) and "name" in m)


class _CatalogCache:
    """TTL-only cache: never serves a stale list as current on failure.

    A failed refresh leaves the previous entries untouched but is always
    re-raised to the caller - the picker must show "Ollama unreachable, edit
    disabled" rather than a list that might no longer be accurate.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._loaded_at: float = 0.0
        self._models: list[str] = []

    def get(self, force_refresh: bool = False) -> list[str]:
        stale = force_refresh or (time.monotonic() - self._loaded_at) >= self._ttl
        if stale:
            self._models = _fetch_tags()
            self._loaded_at = time.monotonic()
        return self._models


_CACHE = _CatalogCache(ttl_seconds=OLLAMA_CATALOG_CACHE_TTL_SECONDS)


def list_available_models(force_refresh: bool = False) -> list[str]:
    """Return installed Ollama tags, cached for OLLAMA_CATALOG_CACHE_TTL_SECONDS.

    Raises OllamaUnreachableError on failure - callers must not fall back to
    a stale list or a free-text field, per the captain's hard constraint.
    """
    return _CACHE.get(force_refresh=force_refresh)
