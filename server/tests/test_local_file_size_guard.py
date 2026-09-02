"""Defect: a local-answering attachment too large for the context window used
to be silently, almost-completely truncated instead of failing clearly.

Repro (QA report): a 60,001-line, 4.5MB .txt file with a marker on line 1
answered as if only the last ~800 lines existed - no error, a confident wrong
answer. Root cause: the local-answering role never passed an explicit
`num_ctx` to Ollama (see config.py's OLLAMA_NUM_CTX comment and
llm_router.py), so Ollama silently dropped the head of the oversized prompt.
This is new exposure the local-attachments feature creates - previously a
file this size always routed external, where a provider accepts the whole
document.

The fix has two parts:
  1. llm_router.py now sets an explicit num_ctx (like every other role), so
     the window Ollama actually uses is a known, generous value instead of
     an undocumented, possibly-tiny default.
  2. openai_compat.py's file-routing decision estimates the inlined prompt's
     token count against that same known budget and routes external instead
     of generating against an overflow - see the size guard next to
     `_file_usable_locally`.

These tests exercise (2) end-to-end; (1) is exercised implicitly (the guard
is only meaningful because the budget it checks against is the real window).
"""
import base64

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.schemas.chat import ExternalLLMResponse
from tests.conftest import StreamingLocalRouterMixin
from tests.test_openai_compat_smoke import (
    _AUTH,
    StubAdjuster,
    StubEnricher,
    StubNormalizer,
    stored_credential,
)

pytestmark = pytest.mark.no_model

QUESTION = "what does the marker say?"
MARKER = "MARKER-VALUE-71-42-19"

# Comfortably under any plausible local-answering budget (num_ctx - max_tokens
# - a small reserve, at a conservative chars/token estimate) - must keep
# routing local, a regression check on top of the existing Stage 1 coverage.
SMALL_FILE = f"{MARKER}\n" + " ".join(f"filler{i}" for i in range(200))

# Comfortably over any plausible budget: ~200K words - the exact repro's
# shape (marker at the very start, answerable only if the model actually saw
# the head of the file) without needing a multi-megabyte fixture on disk.
LARGE_FILE = f"{MARKER}\n" + " ".join(f"filler{i}" for i in range(200_000))


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )
    monkeypatch.setattr(_KEY_CACHE, "namespace", lambda *a, **kw: "test-namespace")


class _NoHitMemory:
    def __init__(self):
        self.stored: list[tuple] = []

    def lookup_cache(self, clean_query: str):
        from app.services.memory_chromaDB import CacheLookupResult

        return CacheLookupResult(hit=False)

    def store_interaction(self, *args, **kwargs):
        self.stored.append((args, kwargs))
        return "id"

    def increment_hit_count(self, doc_id: str):
        return None

    def count_file_entries(self, file_sha: str) -> int:
        return 0


class FactCapturingRouter(StreamingLocalRouterMixin):
    def __init__(self):
        self.called = False
        self.last_query: str | None = None

    async def generate_local_response(self, query: str, history=None, max_tokens=1024, system_prompt=None):
        self.called = True
        self.last_query = query
        if MARKER in query:
            return MARKER, 12.0, "stop"
        return "I don't have that information.", 12.0, "stop"


class CapturingExternalLLM:
    def __init__(self):
        self.request = None

    async def generate_response(self, request, provider=None, api_key=None):
        self.request = request
        return ExternalLLMResponse(
            text=MARKER if MARKER in request.query else "I don't have that information.",
            model_used=request.model,
            prompt_tokens=5,
            completion_tokens=6,
            latency_ms=10.0,
        )


class ExplodingExternalLLM:
    async def generate_response(self, request, provider=None, api_key=None):
        raise AssertionError("external route must not be used for a small, locally-answerable file")


def _patch_local_only(monkeypatch, router, memory=None):
    async def _noop_log(*a, **k):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", router)
    monkeypatch.setattr(openai_compat, "_external_llm", ExplodingExternalLLM())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: memory or _NoHitMemory())
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(
            external_model=None, routing_threshold=0.9,
        ),
    )
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)


def _patch_external_with_credential(monkeypatch, router, external, memory):
    async def _noop_log(*a, **k):
        return None

    monkeypatch.setattr(openai_compat, "_enricher", StubEnricher())
    monkeypatch.setattr(openai_compat, "_normalizer", StubNormalizer())
    monkeypatch.setattr(openai_compat, "_adjuster", StubAdjuster())
    monkeypatch.setattr(openai_compat, "_llm_router", router)
    monkeypatch.setattr(openai_compat, "_external_llm", external)
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: memory)
    monkeypatch.setattr(
        openai_compat,
        "_read_effective_llm_config",
        lambda workspace_slug, workspace_id: openai_compat.EffectiveLlmConfig(
            external_model="claude-sonnet-4-6", routing_threshold=0.9,
        ),
    )
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat.cache_filter, "should_cache", lambda enriched, clean, **kw: (False, "test"))
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)
    monkeypatch.setattr("app.config.CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(
        openai_compat, "get_workspace_provider_key",
        stored_credential("sk-ant-live", providers=("anthropic",)),
    )


def _post_file(query: str, data: bytes, *, filename: str):
    part = {
        "type": "input_file",
        "filename": filename,
        "file_data": "data:text/plain;base64," + base64.b64encode(data).decode(),
    }
    return TestClient(app, headers=_AUTH).post(
        "/v1/responses",
        json={
            "model": "gpt-4o",
            "input": [{"role": "user", "content": [{"type": "input_text", "text": query}, part]}],
            "stream": False,
        },
    )


def test_small_file_still_routes_local_with_no_external_credential(monkeypatch, caplog):
    """Regression: the size guard must not affect files that comfortably fit."""
    router = FactCapturingRouter()
    _patch_local_only(monkeypatch, router)

    with caplog.at_level("INFO", logger="dejaq.router.openai_compat"):
        resp = _post_file(QUESTION, SMALL_FILE.encode(), filename="small.txt")

    assert resp.status_code == 200
    assert resp.json()["output_text"] == MARKER
    assert router.called is True

    done_line = next(
        r.message for r in caplog.records
        if r.name == "dejaq.router.openai_compat" and r.message.startswith("done cache=miss")
    )
    assert "route=local" in done_line


def test_oversized_file_routes_external_instead_of_truncating_silently(monkeypatch, caplog):
    """The headline fix: a file too large for the local context window must
    never be answered locally from a silently-truncated prompt. With a
    credential configured it answers completely via the external route
    instead (the marker, on line 1, is not lost - proving nothing was cut)."""
    router = FactCapturingRouter()
    external = CapturingExternalLLM()
    memory = _NoHitMemory()
    _patch_external_with_credential(monkeypatch, router, external, memory)

    with caplog.at_level("INFO", logger="dejaq.router.openai_compat"):
        resp = _post_file(QUESTION, LARGE_FILE.encode(), filename="large.txt")

    assert resp.status_code == 200
    assert resp.json()["output_text"] == MARKER, "the external route must see the whole file, marker included"
    assert router.called is False, "local generation must never run against a prompt too large for its window"
    assert MARKER in external.request.query

    done_line = next(
        r.message for r in caplog.records
        if r.name == "dejaq.router.openai_compat" and r.message.startswith("done cache=miss")
    )
    assert "route=external" in done_line
    assert any(
        "too large for local answering" in r.message for r in caplog.records
    ), "the reroute must be diagnosable from the log, not silent"


def test_oversized_file_fails_clearly_with_no_external_credential(monkeypatch):
    """No credential configured: the oversized file must still fail with a
    clear, honest error - never silently answered locally from a truncated
    prompt as though it had been read in full."""
    router = FactCapturingRouter()
    _patch_local_only(monkeypatch, router)

    resp = _post_file(QUESTION, LARGE_FILE.encode(), filename="large.txt")

    assert resp.status_code == 422
    assert "no external model configured" in resp.json()["detail"].lower()
    assert router.called is False, "local generation must never run against a prompt too large for its window"
