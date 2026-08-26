"""Regression guards for a silently absorbed cache write.

Reproduced end to end against a running stack before the fix: a store that
raises returns the user a normal 200 carrying an `X-DejaQ-Response-Id` for an
entry that was never written (feedback on it answers 404), and the only trace
anywhere is one `background_store status=failed` ERROR line - no metric, no
counter. That is how a plain `TypeError` from a signature mismatch (48db1e9)
survived: two test doubles did not accept a new argument, and the resulting
defect was indistinguishable from a ChromaDB blip.

These tests assert the OBSERVABLE behaviour - what the client gets, and what a
reader of the stats DB can see - not the shape of the handler.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from tests.conftest import StreamingLocalRouterMixin
from tests.test_openai_compat_smoke import (
    _AUTH,
    StubAdjuster,
    StubEnricher,
    StubMemory,
    StubNormalizer,
)


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    """Make the Bearer token in _AUTH resolve (autouse fixtures don't cross modules)."""
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )


class AnsweringRouter(StreamingLocalRouterMixin):
    async def generate_local_response(self, query, history=None, max_tokens=1024, system_prompt=None):
        return "The capital of France is Paris.", 12.0, "stop"


class FailingMemory(StubMemory):
    """A store that raises - the injected fault, exactly as reproduced live."""

    def __init__(self, exc: Exception):
        self._exc = exc

    def store_interaction(self, *a, **kw):
        raise self._exc


def _patch_common(monkeypatch, memory):
    async def _noop_log(*a, **k):
        return None

    monkeypatch.setattr(
        openai_compat, "_services_for_model_profile",
        lambda profile, llm_config=None: openai_compat.ModelServices(
            normalizer=StubNormalizer(), llm_router=AnsweringRouter(),
            adjuster=StubAdjuster(), enricher=StubEnricher(), validator=None,
        ),
    )
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (True, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)


def _ask(client):
    return client.post(
        "/v1/chat/completions",
        headers={"X-DejaQ-Routing-Mode": "easy_local"},
        json={
            "model": "m",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "stream": False,
        },
    )


def _failures(db_path) -> list[tuple]:
    con = sqlite3.connect(db_path)
    try:
        return con.execute(
            "SELECT workspace, namespace, doc_id, error_type FROM cache_store_failures"
        ).fetchall()
    finally:
        con.close()


def test_a_transient_store_failure_is_counted(monkeypatch, isolated_stats_db):
    """ChromaDB briefly unreachable: the answer still reaches the user, and the
    failed write is now a row somebody can count instead of one log line."""
    _patch_common(monkeypatch, FailingMemory(ConnectionError("chroma unreachable")))

    with TestClient(app, headers=_AUTH) as client:
        response = _ask(client)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "The capital of France is Paris."

    rows = _failures(isolated_stats_db)
    assert len(rows) == 1, f"a failed cache write went uncounted: {rows}"
    workspace, namespace, doc_id, error_type = rows[0]
    assert error_type == "ConnectionError"
    assert workspace == "demo"
    assert doc_id and namespace


def test_a_programming_error_is_not_absorbed(monkeypatch, isolated_stats_db):
    """The 48db1e9 shape: a store called with an argument it does not accept.

    That is a defect, not a runtime condition, so it must escape the handler
    loudly. It is still counted on the way out - the entry is just as missing
    as in the transient case.
    """
    boom = TypeError("store_interaction() got an unexpected keyword argument 'rag_group_key'")
    _patch_common(monkeypatch, FailingMemory(boom))

    with pytest.raises(TypeError, match="rag_group_key"):
        with TestClient(app, headers=_AUTH) as client:
            _ask(client)

    rows = _failures(isolated_stats_db)
    assert len(rows) == 1, f"a failed cache write went uncounted: {rows}"
    assert rows[0][3] == "TypeError"


def test_a_successful_store_counts_nothing(monkeypatch, isolated_stats_db):
    """The counter has to mean something: normal traffic must leave it at zero."""

    class RecordingMemory(StubMemory):
        def __init__(self):
            self.stored = []

        def store_interaction(self, clean_query, generalized_answer, original_query, user_id, **kw):
            self.stored.append(clean_query)
            return "doc123"

    memory = RecordingMemory()
    _patch_common(monkeypatch, memory)

    with TestClient(app, headers=_AUTH) as client:
        response = _ask(client)

    assert response.status_code == 200
    assert memory.stored, "nothing was stored, so this test proves nothing"
    assert _failures(isolated_stats_db) == []
